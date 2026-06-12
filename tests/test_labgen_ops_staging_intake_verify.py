"""
Tests for scripts/labgen_ops_staging_intake_verify.py

Coverage targets:
  - .env.staging.example → BLOCKED_MISSING_INPUTS
  - full fake env (mock helpers) → READY in offline mode
  - missing ADMIN_TOKEN → BLOCKED_MISSING_INPUTS
  - placeholder PROXMOX_TOKEN_SECRET → BLOCKED_MISSING_INPUTS
  - provisioning validate failure → BLOCKED_INVALID_CONFIG
  - production preflight failure → BLOCKED_INVALID_CONFIG
  - base-url diagnostics unreachable → BLOCKED_DIAGNOSTICS_UNREACHABLE
  - base-url diagnostics invalid JSON → BLOCKED_DIAGNOSTICS_UNREACHABLE
  - diagnostics secret leak → BLOCKED_SECRET_LEAK_RISK
  - helper never calls destructive endpoints
  - helper never prints secret values
  - JSON output schema stable
  - no real network calls in any test
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Ensure scripts/ is on the path
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = str(Path(__file__).parent.parent / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from labgen_ops_staging_intake_verify import (  # noqa: E402
    DECISION_READY,
    DECISION_BLOCKED_MISSING,
    DECISION_BLOCKED_CONFIG,
    DECISION_BLOCKED_UNREACHABLE,
    DECISION_BLOCKED_SECRET_LEAK,
    IntakePhaseResult,
    IntakeVerificationResult,
    run_intake_verification,
    _run_phase0,
    _run_phase1,
    _run_phase2,
    _run_phase3,
    _run_phase4,
    _run_phase5,
    _determine_decision,
    _SAFE_GET_CHECKS,
    _FORBIDDEN_PATHS,
    _json_output,
)
from labgen_staging_missing_inputs import (  # noqa: E402
    MissingInputsResult,
    MissingInputGroupResult,
)
from labgen_staging_provisioning_validate import (  # noqa: E402
    ProvisioningResult,
    ProvisioningIssue,
)
from labgen_production_preflight import (  # noqa: E402
    PreflightReport,
    PreflightCheck,
)
from labgen_staging_dry_run import DryRunReport, DryRunCheck  # noqa: E402

pytestmark = pytest.mark.static

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_STAGING_EXAMPLE = _REPO_ROOT / "deploy" / "labgen" / ".env.staging.example"

# ---------------------------------------------------------------------------
# Mock builder helpers
# ---------------------------------------------------------------------------


def _make_pass_missing_inputs(env_file: str) -> MissingInputsResult:
    """Return a passing MissingInputsResult (no missing keys)."""
    return MissingInputsResult(
        overall="pass",
        missing_count=0,
        groups={},
        all_missing_keys=[],
        env_file=env_file,
        checked_at="2026-01-01T00:00:00+00:00",
    )


def _make_blocking_missing_inputs(
    env_file: str,
    missing_keys: list[str],
) -> MissingInputsResult:
    """Return a blocking MissingInputsResult."""
    return MissingInputsResult(
        overall="blocking",
        missing_count=len(missing_keys),
        groups={},
        all_missing_keys=missing_keys,
        env_file=env_file,
        checked_at="2026-01-01T00:00:00+00:00",
    )


def _make_pass_provisioning() -> ProvisioningResult:
    result = ProvisioningResult()
    result.overall = "pass"
    result.checked_at = "2026-01-01T00:00:00+00:00"
    return result


def _make_blocking_provisioning(check: str, message: str) -> ProvisioningResult:
    result = ProvisioningResult()
    result.block(check=check, message=message)
    result.checked_at = "2026-01-01T00:00:00+00:00"
    return result


def _make_pass_preflight() -> PreflightReport:
    report = PreflightReport()
    report.add(PreflightCheck(name="runtime_mode_valid", severity="pass", message="LABGEN_RUNTIME_MODE=production"))
    return report


def _make_blocking_preflight(name: str, message: str) -> PreflightReport:
    report = PreflightReport()
    report.add(PreflightCheck(name=name, severity="blocking", message=message))
    return report


def _make_pass_dry_run() -> DryRunReport:
    report = DryRunReport()
    report.add(DryRunCheck(phase="env_load", name="env_file_loaded", severity="pass", message="Mock pass"))
    return report


def _make_blocking_dry_run(phase: str, name: str, message: str) -> DryRunReport:
    report = DryRunReport()
    report.add(DryRunCheck(phase=phase, name=name, severity="blocking", message=message))
    return report


# ---------------------------------------------------------------------------
# Fixture: complete env file that passes static checks (no secrets in file)
# ---------------------------------------------------------------------------

_COMPLETE_ENV_CONTENT = """\
LABGEN_RUNTIME_MODE=production
LABGEN_NAMESPACE_ADAPTER=k8s
LABGEN_LLM_PROVIDER_MODE=fake_only
LABGEN_LAB_SESSION_TTL_MINUTES=30
LABGEN_VERIFIER_CREDENTIAL_ROOT=/var/lib/labgen-staging/verifier-credentials
PROXMOX_HOST=staging-proxmox.example.internal
PROXMOX_TOKEN_ID=staging@pve!api
ADMIN_USERNAMES=admin
SESSION_COOKIE_SECURE=true
ALLOWED_ORIGINS=http://staging.example.internal:8000
LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/var/lib/labgen-staging/kubeconfig.yaml
# PROXMOX_TOKEN_SECRET=<set-in-secret-manager>
# ADMIN_TOKEN=<set-in-secret-manager>
# VM_SSH_PASSWORD=<set-in-secret-manager>
# VM_REGISTRY_MIRROR=<set-in-secret-manager>
"""


# ---------------------------------------------------------------------------
# Test 1: .env.staging.example → BLOCKED_MISSING_INPUTS
# ---------------------------------------------------------------------------


def test_staging_example_blocked_missing_inputs():
    """The staging example template has placeholders — always BLOCKED_MISSING_INPUTS."""
    assert _STAGING_EXAMPLE.exists(), f"Staging example not found: {_STAGING_EXAMPLE}"
    result = run_intake_verification(str(_STAGING_EXAMPLE))
    assert result.decision == DECISION_BLOCKED_MISSING, (
        f"Expected BLOCKED_MISSING_INPUTS, got {result.decision}"
    )
    # Phase 1 should be blocking
    p1 = result.phase_results["phase1_missing_inputs"]
    assert p1.status == "blocking"
    assert p1.extra.get("missing_count", 0) > 0


# ---------------------------------------------------------------------------
# Test 2: full fake env (mock helpers) → READY in offline mode
# ---------------------------------------------------------------------------


def test_full_fake_env_ready_offline(tmp_path):
    """With all mock helpers returning pass, decision is READY (no base_url)."""
    env_file = tmp_path / ".env.staging"
    env_file.write_text(_COMPLETE_ENV_CONTENT)

    result = run_intake_verification(
        str(env_file),
        base_url=None,
        _missing_inputs_fn=lambda f: _make_pass_missing_inputs(f),
        _validate_env_file_fn=lambda f: _make_pass_provisioning(),
        _run_preflight_fn=_make_pass_preflight,
        _dry_run_offline_fn=lambda f, **kw: _make_pass_dry_run(),
    )

    assert result.decision == DECISION_READY, (
        f"Expected READY, got {result.decision}. "
        f"Blocking: {result.blocking_issues}"
    )
    assert result.phase_results["phase5_diagnostics"] is None  # no base_url → skipped
    assert result.blocking_issues == []


# ---------------------------------------------------------------------------
# Test 3: missing ADMIN_TOKEN → BLOCKED_MISSING_INPUTS
# ---------------------------------------------------------------------------


def test_missing_admin_token_blocked(tmp_path):
    """Missing ADMIN_TOKEN in env file → BLOCKED_MISSING_INPUTS."""
    env_file = tmp_path / ".env.staging"
    env_file.write_text(
        "LABGEN_RUNTIME_MODE=production\n"
        "LABGEN_NAMESPACE_ADAPTER=k8s\n"
        "LABGEN_LLM_PROVIDER_MODE=fake_only\n"
        "LABGEN_LAB_SESSION_TTL_MINUTES=30\n"
        "LABGEN_VERIFIER_CREDENTIAL_ROOT=/var/lib/labgen-staging/verifier-credentials\n"
        "PROXMOX_HOST=staging.internal\n"
        "PROXMOX_TOKEN_ID=staging@pve!api\n"
        "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/var/lib/labgen-staging/kubeconfig.yaml\n"
        # ADMIN_TOKEN is absent entirely
    )

    result = run_intake_verification(str(env_file))
    assert result.decision == DECISION_BLOCKED_MISSING
    p1 = result.phase_results["phase1_missing_inputs"]
    assert p1.status == "blocking"
    assert "ADMIN_TOKEN" in p1.extra.get("missing_keys", [])


# ---------------------------------------------------------------------------
# Test 4: placeholder PROXMOX_TOKEN_SECRET → BLOCKED_MISSING_INPUTS
# ---------------------------------------------------------------------------


def test_placeholder_proxmox_token_secret_blocked(tmp_path):
    """PROXMOX_TOKEN_SECRET=<placeholder> → treated as missing → BLOCKED_MISSING_INPUTS."""
    env_file = tmp_path / ".env.staging"
    env_file.write_text(
        "LABGEN_RUNTIME_MODE=production\n"
        "LABGEN_NAMESPACE_ADAPTER=k8s\n"
        "LABGEN_LLM_PROVIDER_MODE=fake_only\n"
        "LABGEN_LAB_SESSION_TTL_MINUTES=30\n"
        "LABGEN_VERIFIER_CREDENTIAL_ROOT=/var/lib/labgen-staging/verifier-credentials\n"
        "PROXMOX_HOST=staging.internal\n"
        "PROXMOX_TOKEN_ID=staging@pve!api\n"
        "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/var/lib/labgen-staging/kubeconfig.yaml\n"
        "PROXMOX_TOKEN_SECRET=<set-in-secret-manager>\n"  # placeholder
        "ADMIN_TOKEN=<set-in-secret-manager>\n"
        "VM_SSH_PASSWORD=<set-in-secret-manager>\n"
    )

    result = run_intake_verification(str(env_file))
    assert result.decision == DECISION_BLOCKED_MISSING
    p1 = result.phase_results["phase1_missing_inputs"]
    assert p1.status == "blocking"
    assert "PROXMOX_TOKEN_SECRET" in p1.extra.get("missing_keys", [])


# ---------------------------------------------------------------------------
# Test 5: provisioning validate failure → BLOCKED_INVALID_CONFIG
# ---------------------------------------------------------------------------


def test_provisioning_validate_failure_blocked_config(tmp_path):
    """When provisioning validate returns blocking, result is BLOCKED_INVALID_CONFIG."""
    env_file = tmp_path / ".env.staging"
    env_file.write_text(_COMPLETE_ENV_CONTENT)

    def mock_validate(f):
        return _make_blocking_provisioning(
            check="namespace_adapter_not_stub",
            message="LABGEN_NAMESPACE_ADAPTER=stub is not allowed for staging trial.",
        )

    result = run_intake_verification(
        str(env_file),
        _missing_inputs_fn=lambda f: _make_pass_missing_inputs(f),
        _validate_env_file_fn=mock_validate,
        _run_preflight_fn=_make_pass_preflight,
        _dry_run_offline_fn=lambda f, **kw: _make_pass_dry_run(),
    )

    assert result.decision == DECISION_BLOCKED_CONFIG
    p2 = result.phase_results["phase2_provisioning_validate"]
    assert p2.status == "blocking"
    assert len(p2.blocking_issues) > 0


# ---------------------------------------------------------------------------
# Test 6: production preflight failure → BLOCKED_INVALID_CONFIG
# ---------------------------------------------------------------------------


def test_production_preflight_failure_blocked_config(tmp_path):
    """When production preflight returns blocking, result is BLOCKED_INVALID_CONFIG."""
    env_file = tmp_path / ".env.staging"
    env_file.write_text(_COMPLETE_ENV_CONTENT)

    def mock_preflight():
        return _make_blocking_preflight(
            name="admin_token_set",
            message="ADMIN_TOKEN is not set. Admin API endpoints will return 503.",
        )

    result = run_intake_verification(
        str(env_file),
        _missing_inputs_fn=lambda f: _make_pass_missing_inputs(f),
        _validate_env_file_fn=lambda f: _make_pass_provisioning(),
        _run_preflight_fn=mock_preflight,
        _dry_run_offline_fn=lambda f, **kw: _make_pass_dry_run(),
    )

    assert result.decision == DECISION_BLOCKED_CONFIG
    p3 = result.phase_results["phase3_production_preflight"]
    assert p3.status == "blocking"
    assert any("admin_token_set" in issue for issue in p3.blocking_issues)


# ---------------------------------------------------------------------------
# Test 7: base-url diagnostics unreachable → BLOCKED_DIAGNOSTICS_UNREACHABLE
# ---------------------------------------------------------------------------


def test_base_url_diagnostics_unreachable(tmp_path):
    """When HTTP GET returns network error, result is BLOCKED_DIAGNOSTICS_UNREACHABLE."""
    env_file = tmp_path / ".env.staging"
    env_file.write_text(_COMPLETE_ENV_CONTENT)

    def mock_http_get(url: str, headers: dict):
        return (0, "", "Connection refused: staging.example.internal:8000")

    result = run_intake_verification(
        str(env_file),
        base_url="http://staging.example.internal:8000",
        http_get=mock_http_get,
        _missing_inputs_fn=lambda f: _make_pass_missing_inputs(f),
        _validate_env_file_fn=lambda f: _make_pass_provisioning(),
        _run_preflight_fn=_make_pass_preflight,
        _dry_run_offline_fn=lambda f, **kw: _make_pass_dry_run(),
    )

    assert result.decision == DECISION_BLOCKED_UNREACHABLE
    p5 = result.phase_results["phase5_diagnostics"]
    assert p5 is not None
    assert p5.status == "blocking"
    assert p5.diag_kind == "unreachable"
    assert len(p5.blocking_issues) > 0


# ---------------------------------------------------------------------------
# Test 8: base-url diagnostics invalid JSON → BLOCKED_DIAGNOSTICS_UNREACHABLE
# ---------------------------------------------------------------------------


def test_base_url_diagnostics_invalid_json(tmp_path):
    """When HTTP GET returns invalid JSON for a JSON endpoint, result is BLOCKED_DIAGNOSTICS_UNREACHABLE."""
    env_file = tmp_path / ".env.staging"
    env_file.write_text(_COMPLETE_ENV_CONTENT)

    call_count = [0]

    def mock_http_get(url: str, headers: dict):
        call_count[0] += 1
        # /api/health returns invalid JSON
        if "/api/health" in url:
            return (200, "not-valid-json-at-all{{{", None)
        # All other endpoints return valid JSON
        return (200, '{"status":"ok"}', None)

    result = run_intake_verification(
        str(env_file),
        base_url="http://staging.example.internal:8000",
        http_get=mock_http_get,
        _missing_inputs_fn=lambda f: _make_pass_missing_inputs(f),
        _validate_env_file_fn=lambda f: _make_pass_provisioning(),
        _run_preflight_fn=_make_pass_preflight,
        _dry_run_offline_fn=lambda f, **kw: _make_pass_dry_run(),
    )

    assert result.decision == DECISION_BLOCKED_UNREACHABLE
    p5 = result.phase_results["phase5_diagnostics"]
    assert p5 is not None
    assert p5.diag_kind == "unreachable"
    assert any("invalid JSON" in issue for issue in p5.blocking_issues)
    assert call_count[0] > 0, "HTTP client was called"


# ---------------------------------------------------------------------------
# Test 9: diagnostics secret leak → BLOCKED_SECRET_LEAK_RISK
# ---------------------------------------------------------------------------


def test_diagnostics_secret_leak_blocked(tmp_path):
    """When diagnostic response contains secret-looking content, result is BLOCKED_SECRET_LEAK_RISK."""
    env_file = tmp_path / ".env.staging"
    env_file.write_text(_COMPLETE_ENV_CONTENT)

    def mock_http_get(url: str, headers: dict):
        # One endpoint leaks a secret pattern
        if "/api/health" in url:
            return (200, '{"status":"ok","key":"sk-ant-api03-ABCDEF1234567890"}', None)
        return (200, '{"status":"ok"}', None)

    result = run_intake_verification(
        str(env_file),
        base_url="http://staging.example.internal:8000",
        http_get=mock_http_get,
        _missing_inputs_fn=lambda f: _make_pass_missing_inputs(f),
        _validate_env_file_fn=lambda f: _make_pass_provisioning(),
        _run_preflight_fn=_make_pass_preflight,
        _dry_run_offline_fn=lambda f, **kw: _make_pass_dry_run(),
    )

    assert result.decision == DECISION_BLOCKED_SECRET_LEAK
    p5 = result.phase_results["phase5_diagnostics"]
    assert p5 is not None
    assert p5.diag_kind == "secret_leak"
    assert len(p5.blocking_issues) > 0


# ---------------------------------------------------------------------------
# Test 10: helper never calls destructive endpoints
# ---------------------------------------------------------------------------


def test_helper_never_calls_destructive_endpoints(tmp_path):
    """Intake verify must never call POST/destructive endpoints regardless of base_url."""
    env_file = tmp_path / ".env.staging"
    env_file.write_text(_COMPLETE_ENV_CONTENT)

    called_urls: list[str] = []
    called_methods: list[str] = []

    def tracking_http_get(url: str, headers: dict):
        called_urls.append(url)
        called_methods.append("GET")  # our interface is always GET
        return (200, '{"status":"ok"}', None)

    run_intake_verification(
        str(env_file),
        base_url="http://staging.example.internal:8000",
        http_get=tracking_http_get,
        _missing_inputs_fn=lambda f: _make_pass_missing_inputs(f),
        _validate_env_file_fn=lambda f: _make_pass_provisioning(),
        _run_preflight_fn=_make_pass_preflight,
        _dry_run_offline_fn=lambda f, **kw: _make_pass_dry_run(),
    )

    # Verify all calls were GET (our function signature enforces this)
    assert all(m == "GET" for m in called_methods), "All calls must be GET"

    # Verify no destructive paths were called
    destructive_fragments = [
        "/seed/demo",
        "/seed",
        "/publish",
        "/start",
        "/complete",
        "/abort",
        "/expire-sessions",
    ]
    for url in called_urls:
        for frag in destructive_fragments:
            assert frag not in url, (
                f"Destructive endpoint called: {url} (contains '{frag}')"
            )

    # Verify only safe paths were called (from _SAFE_GET_CHECKS)
    safe_paths = {path for _, path, _, _, _ in _SAFE_GET_CHECKS}
    base = "http://staging.example.internal:8000"
    for url in called_urls:
        path = url[len(base):]
        assert path in safe_paths, (
            f"Unexpected path called: {path} — not in safe GET checks"
        )


# ---------------------------------------------------------------------------
# Test 11: helper never prints secret values
# ---------------------------------------------------------------------------


def test_helper_never_prints_secret_values(tmp_path):
    """Secret values must not appear anywhere in the JSON output."""
    FAKE_SECRET = "SUPER_SECRET_STAGING_TOKEN_ABCDEF_1234567890"

    env_file = tmp_path / ".env.staging"
    env_file.write_text(
        "LABGEN_RUNTIME_MODE=production\n"
        f"ADMIN_TOKEN={FAKE_SECRET}\n"  # active secret (will trigger provisioning block)
        "LABGEN_NAMESPACE_ADAPTER=k8s\n"
        "LABGEN_LLM_PROVIDER_MODE=fake_only\n"
        "LABGEN_LAB_SESSION_TTL_MINUTES=30\n"
        "LABGEN_VERIFIER_CREDENTIAL_ROOT=/var/lib/labgen-staging/verifier-credentials\n"
        "PROXMOX_HOST=staging.internal\n"
        "PROXMOX_TOKEN_ID=staging@pve!api\n"
        "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH=/var/lib/labgen-staging/kubeconfig.yaml\n"
    )

    # Run with default helpers (provisioning validate will block on secret in file)
    result = run_intake_verification(str(env_file))

    # Serialize to JSON and verify no secret appears
    output_json = json.dumps(result.to_dict())
    assert FAKE_SECRET not in output_json, (
        f"Secret value found in JSON output! "
        f"Secret: {FAKE_SECRET!r}"
    )

    # Verify secret not in any field recursively
    def _check_no_secret(obj, secret: str) -> None:
        if isinstance(obj, str):
            assert secret not in obj, f"Secret found in string: {obj!r}"
        elif isinstance(obj, dict):
            for v in obj.values():
                _check_no_secret(v, secret)
        elif isinstance(obj, list):
            for item in obj:
                _check_no_secret(item, secret)

    _check_no_secret(result.to_dict(), FAKE_SECRET)


# ---------------------------------------------------------------------------
# Test 12: JSON output schema stable
# ---------------------------------------------------------------------------


def test_json_output_schema_stable(tmp_path):
    """JSON output must contain all required top-level fields."""
    env_file = tmp_path / ".env.staging"
    env_file.write_text(_COMPLETE_ENV_CONTENT)

    result = run_intake_verification(
        str(env_file),
        _missing_inputs_fn=lambda f: _make_pass_missing_inputs(f),
        _validate_env_file_fn=lambda f: _make_pass_provisioning(),
        _run_preflight_fn=_make_pass_preflight,
        _dry_run_offline_fn=lambda f, **kw: _make_pass_dry_run(),
    )

    d = result.to_dict()

    required_top_level = {
        "decision", "phase_results", "blocking_issues", "warnings",
        "checked_at", "next_step", "env_file", "base_url",
    }
    assert required_top_level <= set(d.keys()), (
        f"Missing top-level keys: {required_top_level - set(d.keys())}"
    )

    # phase_results must contain all 6 phases
    pr = d["phase_results"]
    required_phases = {
        "phase0_env_readability",
        "phase1_missing_inputs",
        "phase2_provisioning_validate",
        "phase3_production_preflight",
        "phase4_dry_run_offline",
        "phase5_diagnostics",
    }
    assert required_phases <= set(pr.keys()), (
        f"Missing phases: {required_phases - set(pr.keys())}"
    )

    # Each non-null phase result must have required fields
    for phase_id, phase_data in pr.items():
        if phase_data is None:
            continue  # phase5_diagnostics is None when no base_url
        assert "status" in phase_data, f"{phase_id} missing 'status'"
        assert "summary" in phase_data, f"{phase_id} missing 'summary'"
        assert "blocking_issues" in phase_data, f"{phase_id} missing 'blocking_issues'"
        assert "warnings" in phase_data, f"{phase_id} missing 'warnings'"

    # decision must be one of the known values
    known_decisions = {
        DECISION_READY,
        DECISION_BLOCKED_MISSING,
        DECISION_BLOCKED_CONFIG,
        DECISION_BLOCKED_UNREACHABLE,
        DECISION_BLOCKED_SECRET_LEAK,
    }
    assert d["decision"] in known_decisions, f"Unknown decision: {d['decision']!r}"

    # checked_at must be ISO-8601 UTC
    assert d["checked_at"].endswith("+00:00") or d["checked_at"].endswith("Z"), (
        f"checked_at not UTC: {d['checked_at']}"
    )


# ---------------------------------------------------------------------------
# Test 13: no real network calls in any test
# ---------------------------------------------------------------------------


def test_no_real_network_calls_offline(tmp_path):
    """Offline mode (no base_url) must make zero HTTP calls."""
    env_file = tmp_path / ".env.staging"
    env_file.write_text(_COMPLETE_ENV_CONTENT)

    http_call_count = [0]

    def fail_if_called(url: str, headers: dict):
        http_call_count[0] += 1
        pytest.fail(f"Unexpected real HTTP call to: {url}")
        return (0, "", "should not be called")

    run_intake_verification(
        str(env_file),
        base_url=None,  # offline
        http_get=fail_if_called,
        _missing_inputs_fn=lambda f: _make_pass_missing_inputs(f),
        _validate_env_file_fn=lambda f: _make_pass_provisioning(),
        _run_preflight_fn=_make_pass_preflight,
        _dry_run_offline_fn=lambda f, **kw: _make_pass_dry_run(),
    )

    assert http_call_count[0] == 0, "Expected zero HTTP calls in offline mode"


# ---------------------------------------------------------------------------
# Additional edge case tests
# ---------------------------------------------------------------------------


def test_env_file_not_found_blocked_missing():
    """Non-existent env file → BLOCKED_MISSING_INPUTS (phase 0 fails)."""
    result = run_intake_verification("/non/existent/.env.staging")
    assert result.decision == DECISION_BLOCKED_MISSING
    p0 = result.phase_results["phase0_env_readability"]
    assert p0.status == "error"
    # All subsequent phases must be skipped
    assert result.phase_results["phase1_missing_inputs"].status == "skipped"
    assert result.phase_results["phase2_provisioning_validate"].status == "skipped"
    assert result.phase_results["phase3_production_preflight"].status == "skipped"
    assert result.phase_results["phase4_dry_run_offline"].status == "skipped"
    assert result.phase_results["phase5_diagnostics"] is None


def test_dry_run_offline_failure_blocked_config(tmp_path):
    """When offline dry run returns blocking, result is BLOCKED_INVALID_CONFIG."""
    env_file = tmp_path / ".env.staging"
    env_file.write_text(_COMPLETE_ENV_CONTENT)

    def mock_dry_run(f, **kw):
        return _make_blocking_dry_run(
            phase="preflight",
            name="k8s_kubeconfig_set",
            message="LABGEN_K8S_PLATFORM_KUBECONFIG_PATH is required when LABGEN_NAMESPACE_ADAPTER=k8s.",
        )

    result = run_intake_verification(
        str(env_file),
        _missing_inputs_fn=lambda f: _make_pass_missing_inputs(f),
        _validate_env_file_fn=lambda f: _make_pass_provisioning(),
        _run_preflight_fn=_make_pass_preflight,
        _dry_run_offline_fn=mock_dry_run,
    )

    assert result.decision == DECISION_BLOCKED_CONFIG
    p4 = result.phase_results["phase4_dry_run_offline"]
    assert p4.status == "blocking"


def test_decision_priority_missing_over_config(tmp_path):
    """BLOCKED_MISSING_INPUTS takes priority over BLOCKED_INVALID_CONFIG."""
    env_file = tmp_path / ".env.staging"
    env_file.write_text(_COMPLETE_ENV_CONTENT)

    def mock_validate(f):
        return _make_blocking_provisioning("some_check", "Some config error")

    result = run_intake_verification(
        str(env_file),
        _missing_inputs_fn=lambda f: _make_blocking_missing_inputs(f, ["ADMIN_TOKEN"]),
        _validate_env_file_fn=mock_validate,
        _run_preflight_fn=_make_pass_preflight,
        _dry_run_offline_fn=lambda f, **kw: _make_pass_dry_run(),
    )

    assert result.decision == DECISION_BLOCKED_MISSING, (
        "MISSING_INPUTS must take priority over INVALID_CONFIG"
    )


def test_decision_priority_secret_leak_over_unreachable(tmp_path):
    """BLOCKED_SECRET_LEAK_RISK takes priority over BLOCKED_DIAGNOSTICS_UNREACHABLE."""
    env_file = tmp_path / ".env.staging"
    env_file.write_text(_COMPLETE_ENV_CONTENT)

    call_n = [0]

    def mock_http_get(url: str, headers: dict):
        call_n[0] += 1
        if "/api/health" in url:
            # Secret leak
            return (200, '{"key":"sk-ant-ABCDEF"}', None)
        # All other endpoints unreachable
        return (0, "", "Connection refused")

    result = run_intake_verification(
        str(env_file),
        base_url="http://staging.example.internal:8000",
        http_get=mock_http_get,
        _missing_inputs_fn=lambda f: _make_pass_missing_inputs(f),
        _validate_env_file_fn=lambda f: _make_pass_provisioning(),
        _run_preflight_fn=_make_pass_preflight,
        _dry_run_offline_fn=lambda f, **kw: _make_pass_dry_run(),
    )

    assert result.decision == DECISION_BLOCKED_SECRET_LEAK, (
        "SECRET_LEAK_RISK must take priority over DIAGNOSTICS_UNREACHABLE"
    )


def test_base_url_with_all_pass(tmp_path):
    """When base_url provided and all diagnostics pass → READY."""
    env_file = tmp_path / ".env.staging"
    env_file.write_text(_COMPLETE_ENV_CONTENT)

    def mock_http_get(url: str, headers: dict):
        return (200, '{"status":"ok","version":"1.0"}', None)

    result = run_intake_verification(
        str(env_file),
        base_url="http://staging.example.internal:8000",
        http_get=mock_http_get,
        _missing_inputs_fn=lambda f: _make_pass_missing_inputs(f),
        _validate_env_file_fn=lambda f: _make_pass_provisioning(),
        _run_preflight_fn=_make_pass_preflight,
        _dry_run_offline_fn=lambda f, **kw: _make_pass_dry_run(),
    )

    assert result.decision == DECISION_READY
    p5 = result.phase_results["phase5_diagnostics"]
    assert p5 is not None
    assert p5.status in ("pass", "warning")


def test_warnings_do_not_block(tmp_path):
    """Phase warnings should not change the final decision to BLOCKED."""
    env_file = tmp_path / ".env.staging"
    env_file.write_text(_COMPLETE_ENV_CONTENT)

    def mock_validate_with_warnings(f):
        result = ProvisioningResult()
        result.warn(check="some_warning", message="This is just a warning")
        result.checked_at = "2026-01-01T00:00:00+00:00"
        return result

    result = run_intake_verification(
        str(env_file),
        _missing_inputs_fn=lambda f: _make_pass_missing_inputs(f),
        _validate_env_file_fn=mock_validate_with_warnings,
        _run_preflight_fn=_make_pass_preflight,
        _dry_run_offline_fn=lambda f, **kw: _make_pass_dry_run(),
    )

    assert result.decision == DECISION_READY
    assert len(result.warnings) > 0  # warnings are present but not blocking


def test_blocked_issues_consolidated_in_result(tmp_path):
    """All phase blocking issues are consolidated in result.blocking_issues."""
    env_file = tmp_path / ".env.staging"
    env_file.write_text(_COMPLETE_ENV_CONTENT)

    def mock_validate(f):
        return _make_blocking_provisioning("check_a", "Message from provisioning")

    result = run_intake_verification(
        str(env_file),
        _missing_inputs_fn=lambda f: _make_pass_missing_inputs(f),
        _validate_env_file_fn=mock_validate,
        _run_preflight_fn=_make_pass_preflight,
        _dry_run_offline_fn=lambda f, **kw: _make_pass_dry_run(),
    )

    assert result.decision == DECISION_BLOCKED_CONFIG
    assert any("Message from provisioning" in issue for issue in result.blocking_issues)


# ---------------------------------------------------------------------------
# Phase unit tests
# ---------------------------------------------------------------------------


def test_run_phase0_pass(tmp_path):
    env_file = tmp_path / ".env.test"
    env_file.write_text("KEY=value\n")
    result = _run_phase0(str(env_file))
    assert result.status == "pass"
    assert result.blocking_issues == []


def test_run_phase0_not_found():
    result = _run_phase0("/does/not/exist/.env")
    assert result.status == "error"
    assert len(result.blocking_issues) > 0


def test_run_phase1_pass(tmp_path):
    env_file = tmp_path / ".env.test"
    env_file.write_text("KEY=value\n")
    result = _run_phase1(str(env_file), lambda f: _make_pass_missing_inputs(f))
    assert result.status == "pass"
    assert result.extra["missing_count"] == 0
    assert result.extra["missing_keys"] == []


def test_run_phase1_blocking(tmp_path):
    env_file = tmp_path / ".env.test"
    env_file.write_text("KEY=value\n")
    result = _run_phase1(
        str(env_file),
        lambda f: _make_blocking_missing_inputs(f, ["ADMIN_TOKEN", "VM_SSH_PASSWORD"]),
    )
    assert result.status == "blocking"
    assert result.extra["missing_count"] == 2
    assert "ADMIN_TOKEN" in result.extra["missing_keys"]
    assert "VM_SSH_PASSWORD" in result.extra["missing_keys"]


def test_run_phase2_pass(tmp_path):
    env_file = tmp_path / ".env.test"
    env_file.write_text("KEY=value\n")
    result = _run_phase2(str(env_file), lambda f: _make_pass_provisioning())
    assert result.status == "pass"
    assert result.extra["blocking_count"] == 0


def test_run_phase2_blocking(tmp_path):
    env_file = tmp_path / ".env.test"
    env_file.write_text("KEY=value\n")
    result = _run_phase2(
        str(env_file),
        lambda f: _make_blocking_provisioning("check_x", "Config is invalid"),
    )
    assert result.status == "blocking"
    assert result.extra["blocking_count"] == 1
    assert any("Config is invalid" in i for i in result.blocking_issues)


def test_run_phase5_pass_all_ok(tmp_path):
    env_file = tmp_path / ".env.test"
    env_file.write_text("ADMIN_TOKEN=a-valid-token\n")

    def ok_http(url, headers):
        return (200, '{"status":"ok"}', None)

    result = _run_phase5(str(env_file), "http://staging.example.internal:8000", ok_http)
    assert result.status in ("pass", "warning")
    assert result.diag_kind is None


def test_run_phase5_network_error_is_unreachable(tmp_path):
    env_file = tmp_path / ".env.test"
    env_file.write_text("ADMIN_TOKEN=a-valid-token\n")

    def err_http(url, headers):
        return (0, "", "Connection refused")

    result = _run_phase5(str(env_file), "http://staging.example.internal:8000", err_http)
    assert result.status == "blocking"
    assert result.diag_kind == "unreachable"


def test_run_phase5_secret_in_response_is_leak(tmp_path):
    env_file = tmp_path / ".env.test"
    env_file.write_text("ADMIN_TOKEN=a-valid-token\n")

    def leak_http(url, headers):
        return (200, '{"key":"sk-ant-api03-SECRETVALUE"}', None)

    result = _run_phase5(str(env_file), "http://staging.example.internal:8000", leak_http)
    assert result.status == "blocking"
    assert result.diag_kind == "secret_leak"


def test_determine_decision_all_pass():
    phases = {
        "phase0_env_readability": IntakePhaseResult("phase0_env_readability", "pass", "ok"),
        "phase1_missing_inputs": IntakePhaseResult("phase1_missing_inputs", "pass", "ok"),
        "phase2_provisioning_validate": IntakePhaseResult("phase2_provisioning_validate", "pass", "ok"),
        "phase3_production_preflight": IntakePhaseResult("phase3_production_preflight", "pass", "ok"),
        "phase4_dry_run_offline": IntakePhaseResult("phase4_dry_run_offline", "pass", "ok"),
        "phase5_diagnostics": None,
    }
    assert _determine_decision(phases) == DECISION_READY


def test_determine_decision_phase0_error():
    phases = {
        "phase0_env_readability": IntakePhaseResult(
            "phase0_env_readability", "error", "not found", blocking_issues=["not found"]
        ),
        "phase1_missing_inputs": IntakePhaseResult("phase1_missing_inputs", "skipped", "skipped"),
        "phase2_provisioning_validate": IntakePhaseResult("phase2_provisioning_validate", "skipped", "skipped"),
        "phase3_production_preflight": IntakePhaseResult("phase3_production_preflight", "skipped", "skipped"),
        "phase4_dry_run_offline": IntakePhaseResult("phase4_dry_run_offline", "skipped", "skipped"),
        "phase5_diagnostics": None,
    }
    assert _determine_decision(phases) == DECISION_BLOCKED_MISSING


def test_determine_decision_phase5_secret_leak():
    phases = {
        "phase0_env_readability": IntakePhaseResult("phase0_env_readability", "pass", "ok"),
        "phase1_missing_inputs": IntakePhaseResult("phase1_missing_inputs", "pass", "ok"),
        "phase2_provisioning_validate": IntakePhaseResult("phase2_provisioning_validate", "pass", "ok"),
        "phase3_production_preflight": IntakePhaseResult("phase3_production_preflight", "pass", "ok"),
        "phase4_dry_run_offline": IntakePhaseResult("phase4_dry_run_offline", "pass", "ok"),
        "phase5_diagnostics": IntakePhaseResult(
            "phase5_diagnostics", "blocking", "secret leak",
            blocking_issues=["secret found"],
            diag_kind="secret_leak",
        ),
    }
    assert _determine_decision(phases) == DECISION_BLOCKED_SECRET_LEAK


def test_determine_decision_phase5_unreachable():
    phases = {
        "phase0_env_readability": IntakePhaseResult("phase0_env_readability", "pass", "ok"),
        "phase1_missing_inputs": IntakePhaseResult("phase1_missing_inputs", "pass", "ok"),
        "phase2_provisioning_validate": IntakePhaseResult("phase2_provisioning_validate", "pass", "ok"),
        "phase3_production_preflight": IntakePhaseResult("phase3_production_preflight", "pass", "ok"),
        "phase4_dry_run_offline": IntakePhaseResult("phase4_dry_run_offline", "pass", "ok"),
        "phase5_diagnostics": IntakePhaseResult(
            "phase5_diagnostics", "blocking", "unreachable",
            blocking_issues=["Connection refused"],
            diag_kind="unreachable",
        ),
    }
    assert _determine_decision(phases) == DECISION_BLOCKED_UNREACHABLE


# ---------------------------------------------------------------------------
# Test: blocked_issues in output don't reveal secrets
# ---------------------------------------------------------------------------

def test_blocking_issues_in_output_never_reveal_values(tmp_path):
    """Blocking issue messages must name keys, not values."""
    FAKE_PROXMOX_SECRET = "SHOULD_NOT_APPEAR_proxmox_secret_ABC"

    env_file = tmp_path / ".env.staging"
    env_file.write_text(
        "LABGEN_RUNTIME_MODE=production\n"
        f"PROXMOX_TOKEN_SECRET={FAKE_PROXMOX_SECRET}\n"  # active secret in file
        "LABGEN_NAMESPACE_ADAPTER=k8s\n"
        "LABGEN_LLM_PROVIDER_MODE=fake_only\n"
        "LABGEN_LAB_SESSION_TTL_MINUTES=30\n"
        "LABGEN_VERIFIER_CREDENTIAL_ROOT=/var/lib/labgen-staging/verifier-credentials\n"
        "PROXMOX_HOST=staging.internal\n"
        "PROXMOX_TOKEN_ID=staging@pve!api\n"
    )

    result = run_intake_verification(str(env_file))
    d = result.to_dict()
    output_str = json.dumps(d)

    assert FAKE_PROXMOX_SECRET not in output_str, (
        "Secret value must not appear in any output field"
    )
