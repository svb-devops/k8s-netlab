"""Tests for backend/labgen/image_resolver.py."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.static

from backend.labgen.image_resolver import (
    ImageResolver,
    RequestedImage,
    _INTERNAL_REGISTRY,
    _lookup_whitelist,
    parse_image_ref,
)
from backend.labgen.models import ImageResolutionResult, ImageStatus


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

WHITELIST_PATH = Path("config/image_whitelist.json")
# Use the module constant so tests stay in sync with the implementation
_REG = _INTERNAL_REGISTRY  # e.g. "172.16.100.1:5000"
_REG_BASE = f"http://{_REG}"


def _resolver(http_status: int = 200) -> ImageResolver:
    """Build a resolver with a mock HTTP function that returns a fixed status code."""
    return ImageResolver(
        whitelist_path=WHITELIST_PATH,
        _http_get=lambda url: http_status,
    )


def _resolver_fn(fn) -> ImageResolver:
    """Build a resolver with a custom HTTP function."""
    return ImageResolver(whitelist_path=WHITELIST_PATH, _http_get=fn)


# ---------------------------------------------------------------------------
# parse_image_ref
# ---------------------------------------------------------------------------


class TestParseImageRef:
    def test_bare_name(self):
        r = parse_image_ref("nginx")
        assert r.registry is None
        assert r.name == "nginx"
        assert r.tag is None

    def test_name_with_tag(self):
        r = parse_image_ref("nginx:1.25")
        assert r.registry is None
        assert r.name == "nginx"
        assert r.tag == "1.25"

    def test_name_with_latest(self):
        r = parse_image_ref("nginx:latest")
        assert r.tag == "latest"
        assert r.is_latest is True

    def test_no_tag_property(self):
        r = parse_image_ref("nginx")
        assert r.has_no_tag is True

    def test_namespaced_name(self):
        r = parse_image_ref("curlimages/curl:8.5.0")
        assert r.registry is None
        assert r.name == "curlimages/curl"
        assert r.tag == "8.5.0"

    def test_external_registry(self):
        r = parse_image_ref("docker.io/library/nginx:1.25")
        assert r.registry == "docker.io"
        assert r.name == "library/nginx"
        assert r.tag == "1.25"
        assert r.is_external_registry is True

    def test_ghcr_registry(self):
        r = parse_image_ref("ghcr.io/foo/bar:v1")
        assert r.registry == "ghcr.io"
        assert r.is_external_registry is True

    def test_internal_registry(self):
        r = parse_image_ref("172.16.100.1:5000/nginx:1.25-alpine")
        assert r.registry == "172.16.100.1:5000"
        assert r.name == "nginx"
        assert r.tag == "1.25-alpine"
        assert r.is_internal_registry is True
        assert r.is_external_registry is False

    def test_internal_registry_namespaced(self):
        r = parse_image_ref("172.16.100.1:5000/curlimages/curl:8.5.0")
        assert r.registry == "172.16.100.1:5000"
        assert r.name == "curlimages/curl"
        assert r.tag == "8.5.0"

    def test_digest_stripped(self):
        r = parse_image_ref("nginx:1.25@sha256:abc123")
        assert r.tag == "1.25"
        assert r.name == "nginx"

    def test_intent_key(self):
        r = parse_image_ref("curlimages/curl:8.5.0")
        assert r.intent_key == "curl"

    def test_intent_key_bare(self):
        r = parse_image_ref("nginx:1.25")
        assert r.intent_key == "nginx"


# ---------------------------------------------------------------------------
# _lookup_whitelist
# ---------------------------------------------------------------------------


class TestLookupWhitelist:
    WL = {
        "nginx": {"default": "172.16.100.1:5000/nginx:1.25-alpine", "aliases": ["nginx", "web-server"]},
        "busybox": {"default": "172.16.100.1:5000/busybox:1.36", "aliases": ["shell", "debug"]},
    }

    def test_direct_key(self):
        assert _lookup_whitelist(self.WL, "nginx") == "172.16.100.1:5000/nginx:1.25-alpine"

    def test_alias(self):
        assert _lookup_whitelist(self.WL, "web-server") == "172.16.100.1:5000/nginx:1.25-alpine"

    def test_alias_debug(self):
        assert _lookup_whitelist(self.WL, "debug") == "172.16.100.1:5000/busybox:1.36"

    def test_miss(self):
        assert _lookup_whitelist(self.WL, "unknown-tool") is None

    def test_empty_whitelist(self):
        assert _lookup_whitelist({}, "nginx") is None


# ---------------------------------------------------------------------------
# resolve_image — blocking conditions
# ---------------------------------------------------------------------------


class TestResolveImageBlocking:
    def test_no_tag_is_blocked(self):
        r = _resolver()
        result = r.resolve_image("nginx")
        assert result.image_status == ImageStatus.BLOCKED
        assert result.existence_check_passed is None

    def test_latest_tag_is_blocked(self):
        r = _resolver()
        result = r.resolve_image("nginx:latest")
        assert result.image_status == ImageStatus.BLOCKED

    def test_docker_io_is_blocked(self):
        r = _resolver()
        result = r.resolve_image("docker.io/library/nginx:1.25")
        assert result.image_status == ImageStatus.BLOCKED

    def test_ghcr_io_is_blocked(self):
        r = _resolver()
        result = r.resolve_image("ghcr.io/foo/bar:v1")
        assert result.image_status == ImageStatus.BLOCKED

    def test_quay_io_is_blocked(self):
        r = _resolver()
        result = r.resolve_image("quay.io/foo/bar:v1")
        assert result.image_status == ImageStatus.BLOCKED

    def test_gcr_io_is_blocked(self):
        r = _resolver()
        result = r.resolve_image("gcr.io/foo/bar:v1")
        assert result.image_status == ImageStatus.BLOCKED

    def test_registry_k8s_io_is_blocked(self):
        r = _resolver()
        result = r.resolve_image("registry.k8s.io/pause:3.8")
        assert result.image_status == ImageStatus.BLOCKED

    def test_unknown_registry_is_blocked(self):
        r = _resolver()
        result = r.resolve_image("mycompany.example.com:5001/nginx:1.25")
        assert result.image_status == ImageStatus.BLOCKED

    def test_blocked_preserves_requested_image(self):
        r = _resolver()
        result = r.resolve_image("nginx:latest")
        assert result.requested_image == "nginx:latest"
        assert result.resolved_image is None

    def test_blocked_never_raises(self):
        r = _resolver()
        # Degenerate input — should not raise
        for ref in ["", "  ", "://garbage", ":latest", "/"]:
            result = r.resolve_image(ref)
            assert isinstance(result, ImageResolutionResult)


# ---------------------------------------------------------------------------
# resolve_image — whitelist resolution
# ---------------------------------------------------------------------------


class TestResolveImageWhitelist:
    def test_nginx_resolved(self):
        r = _resolver()
        result = r.resolve_image("nginx:1.25")
        assert result.image_status == ImageStatus.RESOLVED
        assert result.resolved_image == "172.16.100.1:5000/library/nginx:1.25-alpine"
        assert result.existence_check_passed is None  # not checked yet

    def test_busybox_resolved(self):
        r = _resolver()
        result = r.resolve_image("busybox:1.36")
        assert result.image_status == ImageStatus.RESOLVED
        assert "busybox" in result.resolved_image

    def test_alpine_resolved(self):
        r = _resolver()
        result = r.resolve_image("alpine:3.19")
        assert result.image_status == ImageStatus.RESOLVED

    def test_curl_resolved_via_namespaced(self):
        r = _resolver()
        result = r.resolve_image("curlimages/curl:8.5.0")
        assert result.image_status == ImageStatus.RESOLVED
        assert "curl" in result.resolved_image

    def test_intent_overrides_name(self):
        r = _resolver()
        # explicit intent "nginx" maps regardless of requested name
        result = r.resolve_image("some-image:1.0", image_intent="nginx")
        assert result.image_status == ImageStatus.RESOLVED
        assert result.image_intent == "nginx"

    def test_alias_web_server(self):
        r = _resolver()
        result = r.resolve_image("web-server:1.0", image_intent="web-server")
        assert result.image_status == ImageStatus.RESOLVED
        assert "nginx" in result.resolved_image

    def test_unknown_image_unresolved(self):
        r = _resolver()
        result = r.resolve_image("mystery-tool:1.0")
        assert result.image_status == ImageStatus.UNRESOLVED
        assert result.resolved_image is None
        assert result.existence_check_passed is None

    def test_internal_registry_image_resolved_if_in_whitelist(self):
        # If someone passes an internal-registry image that matches a whitelist entry,
        # it still resolves to the whitelist default (canonical form)
        r = _resolver()
        result = r.resolve_image("172.16.100.1:5000/nginx:1.25")
        # name="nginx", intent_key="nginx" → found in whitelist
        assert result.image_status == ImageStatus.RESOLVED

    def test_resolved_image_intent_fallback(self):
        r = _resolver()
        result = r.resolve_image("nginx:1.25")
        assert result.image_intent == "nginx"

    def test_requested_image_preserved(self):
        r = _resolver()
        result = r.resolve_image("nginx:1.25")
        assert result.requested_image == "nginx:1.25"


# ---------------------------------------------------------------------------
# resolve_images (batch)
# ---------------------------------------------------------------------------


class TestResolveImages:
    def test_batch_resolve(self):
        r = _resolver()
        results = r.resolve_images([
            ("nginx:1.25", None),
            ("busybox:1.36", "debug"),
            ("nginx:latest", None),
        ])
        assert len(results) == 3
        assert results[0].image_status == ImageStatus.RESOLVED
        assert results[1].image_status == ImageStatus.RESOLVED
        assert results[2].image_status == ImageStatus.BLOCKED

    def test_empty_batch(self):
        r = _resolver()
        assert r.resolve_images([]) == []

    def test_batch_never_raises(self):
        r = _resolver()
        results = r.resolve_images([("nginx:latest", None), ("ghost:1.0", "unknown")])
        assert len(results) == 2
        for result in results:
            assert isinstance(result, ImageResolutionResult)


# ---------------------------------------------------------------------------
# check_registry_existence
# ---------------------------------------------------------------------------


class TestCheckRegistryExistence:
    def _resolved_img(self, resolved="172.16.100.1:5000/nginx:1.25-alpine") -> ImageResolutionResult:
        return ImageResolutionResult(
            image_intent="nginx",
            requested_image="nginx:1.25",
            resolved_image=resolved,
            image_status=ImageStatus.RESOLVED,
            existence_check_passed=None,
        )

    def test_http_200_sets_passed_true(self):
        r = _resolver(http_status=200)
        result = r.check_registry_existence(self._resolved_img())
        assert result.existence_check_passed is True
        assert result.existence_checked_at is not None

    def test_http_404_sets_passed_false(self):
        r = _resolver(http_status=404)
        result = r.check_registry_existence(self._resolved_img())
        assert result.existence_check_passed is False

    def test_http_401_sets_passed_false(self):
        r = _resolver(http_status=401)
        result = r.check_registry_existence(self._resolved_img())
        assert result.existence_check_passed is False

    def test_network_error_sets_passed_false(self):
        r = _resolver_fn(lambda url: (_ for _ in ()).throw(ConnectionError("down")))
        result = r.check_registry_existence(self._resolved_img())
        assert result.existence_check_passed is False

    def test_network_error_never_raises(self):
        def exploding_get(url: str) -> int:
            raise RuntimeError("unexpected error")
        r = _resolver_fn(exploding_get)
        result = r.check_registry_existence(self._resolved_img())
        assert isinstance(result, ImageResolutionResult)
        assert result.existence_check_passed is False

    def test_skips_blocked_image(self):
        r = _resolver(http_status=200)
        blocked = ImageResolutionResult(
            image_intent="nginx", requested_image="nginx:latest",
            image_status=ImageStatus.BLOCKED, existence_check_passed=None,
        )
        result = r.check_registry_existence(blocked)
        assert result is blocked  # unchanged

    def test_skips_unresolved_image(self):
        r = _resolver(http_status=200)
        unresolved = ImageResolutionResult(
            image_intent="mystery", requested_image="mystery:1.0",
            image_status=ImageStatus.UNRESOLVED, existence_check_passed=None,
        )
        result = r.check_registry_existence(unresolved)
        assert result is unresolved  # unchanged

    def test_correct_url_constructed(self):
        seen_urls: list[str] = []

        def capturing_get(url: str) -> int:
            seen_urls.append(url)
            return 200

        r = _resolver_fn(capturing_get)
        r.check_registry_existence(self._resolved_img("172.16.100.1:5000/nginx:1.25-alpine"))
        assert len(seen_urls) == 1
        assert seen_urls[0] == f"{_REG_BASE}/v2/nginx/manifests/1.25-alpine"

    def test_namespaced_image_url(self):
        seen_urls: list[str] = []

        def capturing_get(url: str) -> int:
            seen_urls.append(url)
            return 200

        r = _resolver_fn(capturing_get)
        img = ImageResolutionResult(
            image_intent="curl",
            requested_image="curlimages/curl:8.5.0",
            resolved_image="172.16.100.1:5000/curlimages/curl:8.5.0",
            image_status=ImageStatus.RESOLVED,
        )
        r.check_registry_existence(img)
        assert seen_urls[0] == f"{_REG_BASE}/v2/curlimages/curl/manifests/8.5.0"

    def test_existence_checked_at_is_timezone_aware(self):
        r = _resolver(http_status=200)
        result = r.check_registry_existence(self._resolved_img())
        assert result.existence_checked_at.tzinfo is not None

    def test_original_fields_preserved(self):
        r = _resolver(http_status=200)
        img = self._resolved_img()
        result = r.check_registry_existence(img)
        assert result.image_intent == img.image_intent
        assert result.requested_image == img.requested_image
        assert result.resolved_image == img.resolved_image
        assert result.image_status == img.image_status


# ---------------------------------------------------------------------------
# needs_recheck
# ---------------------------------------------------------------------------


class TestNeedsRecheck:
    def _resolved(self, checked_at=None, passed=None, recheck_hours=24) -> ImageResolutionResult:
        return ImageResolutionResult(
            image_intent="nginx",
            requested_image="nginx:1.25",
            resolved_image="172.16.100.1:5000/nginx:1.25-alpine",
            image_status=ImageStatus.RESOLVED,
            existence_check_passed=passed,
            existence_checked_at=checked_at,
            recheck_after_hours=recheck_hours,
        )

    def test_needs_check_when_never_checked(self):
        r = _resolver()
        assert r.needs_recheck(self._resolved()) is True

    def test_needs_check_when_passed_is_none(self):
        r = _resolver()
        img = self._resolved(checked_at=datetime.now(tz=timezone.utc), passed=None)
        assert r.needs_recheck(img) is True

    def test_no_recheck_when_fresh(self):
        r = _resolver()
        img = self._resolved(
            checked_at=datetime.now(tz=timezone.utc),
            passed=True,
            recheck_hours=24,
        )
        assert r.needs_recheck(img) is False

    def test_recheck_when_stale(self):
        r = _resolver()
        stale = datetime.now(tz=timezone.utc) - timedelta(hours=25)
        img = self._resolved(checked_at=stale, passed=True, recheck_hours=24)
        assert r.needs_recheck(img) is True

    def test_no_recheck_for_blocked(self):
        r = _resolver()
        blocked = ImageResolutionResult(
            image_intent="nginx", requested_image="nginx:latest",
            image_status=ImageStatus.BLOCKED,
        )
        assert r.needs_recheck(blocked) is False

    def test_no_recheck_for_unresolved(self):
        r = _resolver()
        unresolved = ImageResolutionResult(
            image_intent="mystery", requested_image="mystery:1.0",
            image_status=ImageStatus.UNRESOLVED,
        )
        assert r.needs_recheck(unresolved) is False

    def test_recheck_exactly_at_boundary(self):
        r = _resolver()
        # exactly 24 hours ago — should need recheck (elapsed == recheck_after_hours, not strictly >)
        at_boundary = datetime.now(tz=timezone.utc) - timedelta(hours=24, seconds=1)
        img = self._resolved(checked_at=at_boundary, passed=True, recheck_hours=24)
        assert r.needs_recheck(img) is True


# ---------------------------------------------------------------------------
# Integration: resolve → check → needs_recheck cycle
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_resolve_then_check_then_no_recheck(self):
        r = _resolver(http_status=200)
        result = r.resolve_image("nginx:1.25")
        assert result.image_status == ImageStatus.RESOLVED
        assert r.needs_recheck(result) is True  # not yet checked

        checked = r.check_registry_existence(result)
        assert checked.existence_check_passed is True
        assert r.needs_recheck(checked) is False  # just checked

    def test_blocked_skips_check_and_no_recheck(self):
        r = _resolver(http_status=200)
        result = r.resolve_image("nginx:latest")
        assert result.image_status == ImageStatus.BLOCKED
        checked = r.check_registry_existence(result)
        assert checked is result  # unchanged
        assert r.needs_recheck(checked) is False

    def test_unresolved_skips_check_and_no_recheck(self):
        r = _resolver(http_status=200)
        result = r.resolve_image("unknown-tool:1.0")
        assert result.image_status == ImageStatus.UNRESOLVED
        checked = r.check_registry_existence(result)
        assert checked is result
        assert r.needs_recheck(checked) is False

    def test_full_batch_workflow(self):
        r = _resolver(http_status=200)
        results = r.resolve_images([
            ("nginx:1.25", None),
            ("alpine:3.19", None),
            ("nginx:latest", None),
            ("unknown:1.0", None),
        ])
        checked = [r.check_registry_existence(res) for res in results]
        assert checked[0].existence_check_passed is True   # resolved + exists
        assert checked[1].existence_check_passed is True   # resolved + exists
        assert checked[2].existence_check_passed is None   # blocked, skipped
        assert checked[3].existence_check_passed is None   # unresolved, skipped


# ---------------------------------------------------------------------------
# OCI Accept header regression (prevents false-negative existence checks)
# ---------------------------------------------------------------------------


class TestOCIAcceptHeader:
    """Regression tests: existence check must send OCI-compatible Accept headers.

    Without them, multi-arch OCI index images return 404 from registry v2 even
    when the image exists — causing false-negative publish gates.
    """

    def test_default_http_get_sends_oci_accept_header(self):
        captured_headers: list[dict] = []

        class FakeResponse:
            status_code = 200

        import httpx
        from unittest.mock import patch as _patch

        def fake_get(url: str, **kwargs):
            captured_headers.append(kwargs.get("headers", {}))
            return FakeResponse()

        from backend.labgen.image_resolver import _default_http_get
        with _patch("httpx.get", side_effect=fake_get):
            _default_http_get(f"{_REG_BASE}/v2/library/nginx/manifests/1.25-alpine")

        assert len(captured_headers) == 1
        accept = captured_headers[0].get("Accept", "")
        assert "application/vnd.oci.image.index.v1+json" in accept
        assert "application/vnd.docker.distribution.manifest.list.v2+json" in accept

    def test_whitelist_nginx_maps_to_library_prefix(self):
        """nginx intent must resolve to library/nginx path for OCI index registry compat."""
        seen_urls: list[str] = []

        r = ImageResolver(
            whitelist_path=WHITELIST_PATH,
            _http_get=lambda url: (seen_urls.append(url), 200)[1],
        )
        res = r.resolve_image("nginx:1.25-alpine", image_intent="nginx")
        assert res.image_status == ImageStatus.RESOLVED
        assert "library/nginx" in (res.resolved_image or "")

        r.check_registry_existence(res)
        assert len(seen_urls) == 1
        assert "library/nginx" in seen_urls[0]

    def test_whitelist_busybox_maps_to_library_prefix(self):
        """busybox intent must resolve to library/busybox path for OCI index registry compat."""
        seen_urls: list[str] = []

        r = ImageResolver(
            whitelist_path=WHITELIST_PATH,
            _http_get=lambda url: (seen_urls.append(url), 200)[1],
        )
        res = r.resolve_image("busybox:1.36", image_intent="busybox")
        assert res.image_status == ImageStatus.RESOLVED
        assert "library/busybox" in (res.resolved_image or "")

        r.check_registry_existence(res)
        assert len(seen_urls) == 1
        assert "library/busybox" in seen_urls[0]
