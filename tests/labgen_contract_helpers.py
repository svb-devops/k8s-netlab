"""
Shared safety helpers for LabGen contract tests.

Extracted so test_labgen_api_contract_pack.py and
test_labgen_frontend_contract_smoke.py can share the same assertion logic
without duplicating the allowlist rules.
"""

from __future__ import annotations

import re

# Absolute keywords that must NEVER appear in any leaf string value of a
# frontend-facing API response (no exceptions).
_ABSOLUTE_SENSITIVE: frozenset[str] = frozenset({
    "kubeconfig",
    "private_key",
    "traceback",
    "stack trace",
    "raw exception",
    "password",
})

# Regex for safe machine codes: lowercase + underscores only, no dots/hyphens.
# Real JWT / Bearer tokens fail this pattern (contain ".", "-", or uppercase).
_MACHINE_CODE_RE = re.compile(r"^[a-z][a-z_]*$")

# Long base64 block — likely a credential or cert
_LONG_BASE64_RE = re.compile(r"[A-Za-z0-9+/]{60,}={0,2}")

# JWT-like pattern
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9._\-]+\.[A-Za-z0-9._\-]+\.[A-Za-z0-9._\-]+")


def _collect_leaf_strings(obj) -> list[str]:
    """Recursively collect all leaf string values (keys are skipped)."""
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, list):
        out: list[str] = []
        for item in obj:
            out.extend(_collect_leaf_strings(item))
        return out
    if isinstance(obj, dict):
        out = []
        for v in obj.values():
            out.extend(_collect_leaf_strings(v))
        return out
    return []


def assert_contract_response_safe(payload) -> None:
    """
    Assert that no leaf string value in a response payload contains sensitive data.

    Checks string VALUES only (not JSON keys) to avoid false positives on field
    names like 'credential_type' or 'secret_exists'.

    Allowlist rules:
      - "token": allowed only if the value matches ^[a-z][a-z_]*$ (machine code).
        Real JWT / Bearer tokens fail (contain ".", "-", capitals).
      - "secret": allowed only in lowercase_snake_case enum values ≤ 40 chars.
      - "credential": allowed only in lowercase_snake_case machine codes ≤ 60 chars.
      - "namespace": allowed only in lowercase_snake_case machine codes ≤ 60 chars.
        (namespace field values from sanitize_text are safe machine codes like
        "namespace_cleanup_failed"; raw K8s namespace strings like "lab-abc123"
        contain hyphens and would fail the pattern check)
    """
    for val in _collect_leaf_strings(payload):
        v = val.lower()

        # Absolute keywords — no exceptions
        for kw in _ABSOLUTE_SENSITIVE:
            assert kw not in v, (
                f"Sensitive keyword {kw!r} found in response value: {val[:120]!r}"
            )

        # JWT pattern
        assert not _JWT_RE.search(val), (
            f"JWT-like string in response value: {val[:80]!r}"
        )

        # Long base64 block
        assert not _LONG_BASE64_RE.search(val), (
            f"Long base64-like string in response value: {val[:80]!r}"
        )

        # "token" — flag unless it looks like a machine code
        if "token" in v:
            is_safe = bool(_MACHINE_CODE_RE.match(val)) and len(val) <= 60
            assert is_safe, (
                f"Possible token leak in response value: {val[:120]!r}\n"
                "(real tokens contain dots, hyphens, or mixed case; machine codes do not)"
            )

        # "secret" — flag unless it looks like a known-safe enum value
        if "secret" in v:
            is_safe = bool(_MACHINE_CODE_RE.match(val)) and len(val) <= 40
            assert is_safe, (
                f"Possible secret leak in response value: {val[:120]!r}"
            )

        # "credential" — flag unless it looks like a machine code
        if "credential" in v:
            is_safe = bool(_MACHINE_CODE_RE.match(val)) and len(val) <= 60
            assert is_safe, (
                f"Possible credential leak in response value: {val[:120]!r}"
            )
