"""
ImageResolver — maps LLM image intent to internal registry images.

Design principle (Contract §7):
  LLM expresses intent only ("need an nginx-type image").
  The system decides the concrete tag via the whitelist.

All failure paths return ImageResolutionResult with appropriate image_status;
no exceptions are raised to the caller.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from backend.labgen.models import ImageResolutionResult, ImageStatus

logger = logging.getLogger(__name__)

# HTTP GET callable type: (url) → status_code (0 on network error)
HttpGetFn = Callable[[str], int]

# Internal registry — the only registry allowed in resolved images
_INTERNAL_REGISTRY = "172.16.100.1:5000"

# Known external registries — always BLOCKED
_EXTERNAL_REGISTRY_PREFIXES = (
    "docker.io",
    "ghcr.io",
    "quay.io",
    "registry.k8s.io",
    "k8s.gcr.io",
    "gcr.io",
    "us-docker.pkg.dev",
    "mcr.microsoft.com",
    "public.ecr.aws",
)

# Registries containing "." or ":" are treated as explicit registry references
_REGISTRY_MARKER_RE = re.compile(r"[.:]")


# ---------------------------------------------------------------------------
# RequestedImage — parsed image reference
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RequestedImage:
    """Parsed Docker image reference."""
    raw: str
    registry: Optional[str]   # e.g., "172.16.100.1:5000" or "docker.io"
    name: str                  # e.g., "nginx" or "library/nginx"
    tag: Optional[str]         # e.g., "1.25-alpine"; None means no tag

    @property
    def is_latest(self) -> bool:
        return self.tag == "latest"

    @property
    def has_no_tag(self) -> bool:
        return self.tag is None

    @property
    def is_external_registry(self) -> bool:
        if self.registry is None:
            return False
        return self.registry != _INTERNAL_REGISTRY

    @property
    def is_internal_registry(self) -> bool:
        return self.registry == _INTERNAL_REGISTRY

    @property
    def intent_key(self) -> str:
        """Best-effort intent key: the last component of the image name without tag."""
        return self.name.split("/")[-1]


def parse_image_ref(image_ref: str) -> RequestedImage:
    """
    Parse a Docker image reference.

    Handles:
      nginx                          → registry=None, name=nginx, tag=None
      nginx:1.25                     → registry=None, name=nginx, tag=1.25
      nginx:latest                   → registry=None, name=nginx, tag=latest
      docker.io/library/nginx:1.25   → registry=docker.io, name=library/nginx, tag=1.25
      172.16.100.1:5000/nginx:1.25   → registry=172.16.100.1:5000, name=nginx, tag=1.25
      curlimages/curl:8.5.0          → registry=None, name=curlimages/curl, tag=8.5.0
    """
    ref = image_ref.strip()

    # Strip digest (@sha256:...) — not supported in MVP
    if "@" in ref:
        ref = ref.split("@")[0]

    # Split path components
    parts = ref.split("/")

    # Extract tag from the last component
    tag: Optional[str] = None
    last = parts[-1]
    if ":" in last:
        name_part, tag = last.rsplit(":", 1)
        parts[-1] = name_part

    # Determine if the first component is a registry:
    # A component is a registry if it contains "." or ":" (port), or is "localhost"
    registry: Optional[str] = None
    if len(parts) > 1 and (
        _REGISTRY_MARKER_RE.search(parts[0]) or parts[0] == "localhost"
    ):
        registry = parts[0]
        name = "/".join(parts[1:])
    else:
        name = "/".join(parts)

    return RequestedImage(raw=image_ref, registry=registry, name=name, tag=tag)


# ---------------------------------------------------------------------------
# Whitelist helpers
# ---------------------------------------------------------------------------


def _load_whitelist(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        logger.warning("image_whitelist.json not found or invalid: %s", exc)
        return {}


def _lookup_whitelist(whitelist: dict, key: str) -> Optional[str]:
    """Return the default resolved image for a given key or alias, or None."""
    # Direct key match
    if key in whitelist:
        return whitelist[key]["default"]
    # Alias match
    for entry in whitelist.values():
        if key in entry.get("aliases", []):
            return entry["default"]
    return None


# ---------------------------------------------------------------------------
# Default HTTP GET (injectable for tests)
# ---------------------------------------------------------------------------


def _default_http_get(url: str) -> int:
    """GET url, return HTTP status code or 0 on any network error."""
    try:
        import httpx
        r = httpx.get(url, timeout=5.0, verify=False)
        return r.status_code
    except Exception as exc:
        logger.debug("Registry HTTP check failed for %s: %s", url, exc)
        return 0


# ---------------------------------------------------------------------------
# ImageResolver
# ---------------------------------------------------------------------------


class ImageResolver:
    """
    Resolves LLM image intents to internal registry images.

    Parameters
    ----------
    whitelist_path:
        Path to config/image_whitelist.json.
    registry_base_url:
        Base URL for registry existence checks (no trailing slash).
        Defaults to http://<internal-registry-host>:5000.
    _http_get:
        Injectable HTTP GET callable (url) → int.  Override in tests to avoid
        real network calls.
    """

    def __init__(
        self,
        whitelist_path: str | Path = "config/image_whitelist.json",
        registry_base_url: str = f"http://{_INTERNAL_REGISTRY}",
        _http_get: Optional[HttpGetFn] = None,
    ) -> None:
        self._whitelist = _load_whitelist(Path(whitelist_path))
        self._registry_base_url = registry_base_url.rstrip("/")
        self._http_get: HttpGetFn = _http_get or _default_http_get

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve_image(
        self,
        requested_image: str,
        image_intent: Optional[str] = None,
    ) -> ImageResolutionResult:
        """
        Resolve a single image reference.

        Returns ImageResolutionResult with:
          - BLOCKED  if latest tag / no tag / external registry / unknown registry
          - UNRESOLVED  if not found in whitelist
          - RESOLVED  if mapped to internal registry

        Never raises; all errors surface in image_status and message fields.
        """
        parsed = parse_image_ref(requested_image)

        # --- Blocking conditions (order matters: cheapest first) ---

        if parsed.has_no_tag:
            return self._blocked(
                parsed,
                image_intent,
                "no tag — pin to a specific version (e.g. nginx:1.25-alpine)",
            )

        if parsed.is_latest:
            return self._blocked(
                parsed,
                image_intent,
                "':latest' tag is forbidden — pin to a specific version",
            )

        if parsed.registry is not None:
            if any(parsed.registry.startswith(ext) for ext in _EXTERNAL_REGISTRY_PREFIXES):
                return self._blocked(
                    parsed,
                    image_intent,
                    f"external registry '{parsed.registry}' is forbidden — use internal registry only",
                )
            if not parsed.is_internal_registry:
                return self._blocked(
                    parsed,
                    image_intent,
                    f"unknown registry '{parsed.registry}' — only '{_INTERNAL_REGISTRY}' is allowed",
                )

        # --- Whitelist lookup ---

        # Priority: explicit intent → parsed intent_key → full name
        lookup_keys: list[str] = []
        if image_intent:
            lookup_keys.append(image_intent)
        lookup_keys.append(parsed.intent_key)
        if parsed.name != parsed.intent_key:
            lookup_keys.append(parsed.name)

        resolved: Optional[str] = None
        for key in lookup_keys:
            resolved = _lookup_whitelist(self._whitelist, key)
            if resolved:
                break

        if resolved is None:
            return ImageResolutionResult(
                image_intent=image_intent or parsed.intent_key,
                requested_image=requested_image,
                resolved_image=None,
                image_status=ImageStatus.UNRESOLVED,
                existence_check_passed=None,
            )

        return ImageResolutionResult(
            image_intent=image_intent or parsed.intent_key,
            requested_image=requested_image,
            resolved_image=resolved,
            image_status=ImageStatus.RESOLVED,
            existence_check_passed=None,  # not yet checked; caller must call check_registry_existence()
        )

    def resolve_images(
        self,
        requests: list[tuple[str, Optional[str]]],
    ) -> list[ImageResolutionResult]:
        """
        Resolve multiple images.

        Parameters
        ----------
        requests:
            List of (requested_image, image_intent) tuples.
            image_intent may be None.
        """
        return [self.resolve_image(img, intent) for img, intent in requests]

    def check_registry_existence(
        self,
        img: ImageResolutionResult,
    ) -> ImageResolutionResult:
        """
        Check whether the resolved image exists in the internal registry.

        Only operates on RESOLVED images with a resolved_image set.
        For BLOCKED/UNRESOLVED images, returns the input unchanged.

        Sets existence_check_passed and existence_checked_at on the result.
        Never raises.
        """
        if img.image_status != ImageStatus.RESOLVED or not img.resolved_image:
            return img

        parsed = parse_image_ref(img.resolved_image)
        if not parsed.tag:
            logger.warning("resolved_image '%s' has no tag — skipping existence check", img.resolved_image)
            return img

        # Build registry path: name may contain slashes (e.g., curlimages/curl)
        url = f"{self._registry_base_url}/v2/{parsed.name}/manifests/{parsed.tag}"

        try:
            status = self._http_get(url)
            passed = status == 200
        except Exception as exc:
            logger.warning("Unexpected error in existence check for %s: %s", url, exc)
            passed = False

        return img.model_copy(update={
            "existence_check_passed": passed,
            "existence_checked_at": datetime.now(tz=timezone.utc),
        })

    def needs_recheck(self, img: ImageResolutionResult) -> bool:
        """
        Return True if the image requires a fresh registry existence check.

        True when:
          - image_status == RESOLVED (only resolved images are checked)
          - AND (existence_check_passed is None
                 OR existence_checked_at is None
                 OR hours since last check > recheck_after_hours)
        """
        if img.image_status != ImageStatus.RESOLVED:
            return False
        if img.existence_check_passed is None or img.existence_checked_at is None:
            return True
        elapsed_hours = (
            datetime.now(tz=timezone.utc) - img.existence_checked_at
        ).total_seconds() / 3600
        return elapsed_hours > img.recheck_after_hours

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _blocked(
        self,
        parsed: RequestedImage,
        image_intent: Optional[str],
        reason: str,
    ) -> ImageResolutionResult:
        return ImageResolutionResult(
            image_intent=image_intent or parsed.intent_key,
            requested_image=parsed.raw,
            resolved_image=None,
            image_status=ImageStatus.BLOCKED,
            existence_check_passed=None,
        )
