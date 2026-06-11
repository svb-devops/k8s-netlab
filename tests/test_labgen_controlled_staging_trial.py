"""
Tests for scripts/labgen_controlled_staging_trial.py.

Coverage targets (per task spec):
  1. Default mode only calls safe GET diagnostics (no POST).
  2. No destructive endpoints called without allow flags.
  3. --allow-runtime-start enables POST /api/lab-sessions.
  4. Missing base-url with allow flags returns structured blocking failure.
  5. Missing --staging-lab-draft-id returns structured blocking failure.
  6. Diagnostics secret leak detected and reported as blocking.
  7. Unsafe adapter status (production_safe=false) causes blocking check.
  8. LLM live_enabled=true causes blocking check.
  9. JSON output schema stable across runs.
 10. Fake HTTP clients (GET + POST) fully injectable.
 11. No real network required.
 12. No secret values printed in any output path.
 13. Expiry phase only runs with --allow-timeout-expiry flag.
 14. Cleanup phase only runs with --allow-cleanup-check flag.
 15. Missing session-id for cleanup returns structured blocking failure.

All tests are pytest.mark.static (no K3s, no LLM, no external network).
"""

from __future__ import annotations

import json
import os
import sys
from io import StringIO
from typing import Optional
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.static

# ---------------------------------------------------------------------------
# Import script module
# ---------------------------------------------------------------------------

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS_DIR = os.path.join(_PROJECT_ROOT, "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import labgen_controlled_staging_trial as trial  # noqa: E402

# ---------------------------------------------------------------------------
# Test fixtures and helpers
# ---------------------------------------------------------------------------

# A staging-like env that passes preflight (warnings acceptable)
_STAGING_ENV: dict[str, str] = {
    "LABGEN_RUNTIME_MODE": "production",
    "LABGEN_NAMESPACE_ADAPTER": "k8s",
    "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH": "/etc/labgen-staging/kubeconfig.yaml",
    "LABGEN_VERIFIER_CREDENTIAL_ROOT": "/var/lib/labgen-staging/verifier-credentials",
    "LABGEN_LLM_PROVIDER_MODE": "fake_only",
    "LABGEN_LAB_SESSION_TTL_MINUTES": "30",
    "PROXMOX_HOST": "staging-proxmox.local",
    "PROXMOX_TOKEN_ID": "labgen-staging@pve!api",
    "PROXMOX_TOKEN_SECRET": "staging-token-secret-value",
    "VM_SSH_PASSWORD": "staging-vm-password",
    "ADMIN_TOKEN": "a" * 36,
    "ADMIN_USERNAMES": "admin",
    "SESSION_COOKIE_SECURE": "false",
    "STAGING_USER_SESSION": "staging-session-cookie-value",
}

_BASE = "http://localhost:19000"


def _fake_get_factory(responses: dict[str, tuple[int, str]]):
    """Injectable GET client with call recorder."""
    calls: list[tuple[str, dict]] = []

    def _fake_get(url: str, headers: dict) -> tuple[int, str, Optional[str]]:
        calls.append((url, dict(headers)))
        if url in responses:
            code, body = responses[url]
            return code, body, None
        return 200, "{}", None

    _fake_get.calls = calls  # type: ignore[attr-defined]
    return _fake_get


def _fake_post_factory(responses: dict[str, tuple[int, str]]):
    """Injectable POST client with call recorder."""
    calls: list[tuple[str, dict, dict]] = []

    def _fake_post(url: str, headers: dict, body: dict) -> tuple[int, str, Optional[str]]:
        calls.append((url, dict(headers), dict(body)))
        if url in responses:
            code, resp_body = responses[url]
            return code, resp_body, None
        return 200, "{}", None

    _fake_post.calls = calls  # type: ignore[attr-defined]
    return _fake_post


def _make_happy_get_responses(base: str) -> dict[str, tuple[int, str]]:
    return {
        f"{base}/api/health": (200, '{"status":"healthy"}'),
        f"{base}/openapi.json": (200, '{"openapi":"3.0.0"}'),
        f"{base}/": (200, "<html></html>"),
        f"{base}/api/labgen/contract-pack": (200, '{"version":"v0.1","endpoints":[]}'),
        f"{base}/api/labgen/runtime/adapter-status": (
            200,
            '{"namespace_adapter_kind":"k8s","production_safe":true,"runtime_mode":"production"}',
        ),
        f"{base}/api/labgen/llm-provider/status": (200, '{"live_enabled":false}'),
    }


def _all_output(report: trial.TrialReport) -> str:
    buf_h = StringIO()
    with patch("sys.stdout", buf_h):
        trial._human_output(report, "diagnostics_only")

    buf_j = StringIO()
    with patch("sys.stdout", buf_j):
        trial._json_output(report, "diagnostics_only")

    return buf_h.getvalue() + buf_j.getvalue()


# ---------------------------------------------------------------------------
# A — Default mode: only safe GET diagnostics
# ---------------------------------------------------------------------------


class TestDefaultModeOnlySafeDiagnostics:
    def test_offline_mode_makes_no_http_calls(self) -> None:
        get_calls: list[str] = []

        def recording_get(url, headers):
            get_calls.append(url)
            return 200, "{}", None

        post_calls: list[str] = []

        def recording_post(url, headers, body):
            post_calls.append(url)
            return 200, "{}", None

        trial.run_trial(
            env_vars=_STAGING_ENV,
            http_get=recording_get,
            http_post=recording_post,
        )
        assert len(get_calls) == 0, "Offline mode must make no GET calls"
        assert len(post_calls) == 0, "Offline mode must make no POST calls"

    def test_base_url_triggers_get_diagnostics(self) -> None:
        get = _fake_get_factory(_make_happy_get_responses(_BASE))
        trial.run_trial(env_vars=_STAGING_ENV, base_url=_BASE, http_get=get)
        assert len(get.calls) > 0, "Diagnostics phase must make GET calls when base_url provided"

    def test_base_url_default_mode_makes_no_post_calls(self) -> None:
        get = _fake_get_factory(_make_happy_get_responses(_BASE))
        post = _fake_post_factory({})
        trial.run_trial(env_vars=_STAGING_ENV, base_url=_BASE, http_get=get, http_post=post)
        assert len(post.calls) == 0, "Default mode must not POST anything"

    def test_diagnostics_phase_checks_present_with_base_url(self) -> None:
        get = _fake_get_factory(_make_happy_get_responses(_BASE))
        report = trial.run_trial(env_vars=_STAGING_ENV, base_url=_BASE, http_get=get)
        diag = [c for c in report.checks if c.phase == trial._PHASE_DIAGNOSTICS]
        assert len(diag) > 0, "Diagnostics phase checks must be present when base_url provided"

    def test_runtime_phase_absent_by_default(self) -> None:
        get = _fake_get_factory(_make_happy_get_responses(_BASE))
        report = trial.run_trial(env_vars=_STAGING_ENV, base_url=_BASE, http_get=get)
        runtime = [c for c in report.checks if c.phase == trial._PHASE_RUNTIME]
        assert len(runtime) == 0, "Runtime phase must not appear without --allow-runtime-start"

    def test_expiry_phase_absent_by_default(self) -> None:
        get = _fake_get_factory(_make_happy_get_responses(_BASE))
        report = trial.run_trial(env_vars=_STAGING_ENV, base_url=_BASE, http_get=get)
        expiry = [c for c in report.checks if c.phase == trial._PHASE_EXPIRY]
        assert len(expiry) == 0, "Expiry phase must not appear without --allow-timeout-expiry"

    def test_cleanup_phase_absent_by_default(self) -> None:
        get = _fake_get_factory(_make_happy_get_responses(_BASE))
        report = trial.run_trial(env_vars=_STAGING_ENV, base_url=_BASE, http_get=get)
        cleanup = [c for c in report.checks if c.phase == trial._PHASE_CLEANUP]
        assert len(cleanup) == 0, "Cleanup phase must not appear without --allow-cleanup-check"


# ---------------------------------------------------------------------------
# B — No destructive endpoints without allow flags
# ---------------------------------------------------------------------------


class TestNoDestructiveWithoutFlags:
    _FORBIDDEN = [
        "/api/labgen/seed/demo",
        "/api/labgen/drafts",
        "/api/lab-sessions",
        "/api/labgen/runtime/expire-sessions",
        "/api/labgen/generate",
        "/api/lab-drafts/generate",
    ]

    def test_no_forbidden_get_calls(self) -> None:
        called_urls: list[str] = []

        def recording_get(url, headers):
            called_urls.append(url)
            return 200, "{}", None

        trial.run_trial(env_vars=_STAGING_ENV, base_url=_BASE, http_get=recording_get)
        for url in called_urls:
            path = url[len(_BASE):]
            for forbidden in self._FORBIDDEN:
                assert not path.startswith(forbidden), \
                    f"Forbidden path called via GET: {url}"

    def test_no_post_calls_without_flags(self) -> None:
        post = _fake_post_factory({})
        trial.run_trial(
            env_vars=_STAGING_ENV,
            base_url=_BASE,
            http_get=_fake_get_factory(_make_happy_get_responses(_BASE)),
            http_post=post,
        )
        assert len(post.calls) == 0, "No POST calls allowed without allow flags"

    def test_seed_demo_never_called(self) -> None:
        called: list[str] = []

        def rec_get(url, headers):
            called.append(url)
            return 200, "{}", None

        trial.run_trial(env_vars=_STAGING_ENV, base_url=_BASE, http_get=rec_get)
        seed_calls = [u for u in called if "seed" in u.lower()]
        assert len(seed_calls) == 0, "Demo seed endpoint must never be called"

    def test_lab_sessions_not_called_without_runtime_flag(self) -> None:
        post = _fake_post_factory({})
        trial.run_trial(
            env_vars=_STAGING_ENV,
            base_url=_BASE,
            http_get=_fake_get_factory(_make_happy_get_responses(_BASE)),
            http_post=post,
        )
        session_posts = [url for url, _, _ in post.calls if "/api/lab-sessions" in url]
        assert len(session_posts) == 0


# ---------------------------------------------------------------------------
# C — Runtime start flag behaviour
# ---------------------------------------------------------------------------


class TestRuntimeStartFlag:
    def test_allow_runtime_start_with_lab_draft_id_posts_to_lab_sessions(self) -> None:
        get = _fake_get_factory(_make_happy_get_responses(_BASE))
        post = _fake_post_factory({
            f"{_BASE}/api/lab-sessions": (201, '{"id":"test-session-id"}'),
        })
        trial.run_trial(
            env_vars=_STAGING_ENV,
            base_url=_BASE,
            allow_runtime_start=True,
            staging_lab_draft_id="test-lab-draft-id",
            http_get=get,
            http_post=post,
        )
        session_posts = [url for url, _, _ in post.calls if url.endswith("/api/lab-sessions")]
        assert len(session_posts) == 1, "Must POST to /api/lab-sessions with allow flag"

    def test_allow_runtime_start_sends_lab_draft_id_in_body(self) -> None:
        get = _fake_get_factory(_make_happy_get_responses(_BASE))
        post = _fake_post_factory({
            f"{_BASE}/api/lab-sessions": (201, '{"id":"sid"}'),
        })
        trial.run_trial(
            env_vars=_STAGING_ENV,
            base_url=_BASE,
            allow_runtime_start=True,
            staging_lab_draft_id="my-lab-uuid",
            http_get=get,
            http_post=post,
        )
        for url, _, body in post.calls:
            if url.endswith("/api/lab-sessions"):
                assert body.get("lab_draft_id") == "my-lab-uuid"

    def test_runtime_start_201_adds_pass_check(self) -> None:
        get = _fake_get_factory(_make_happy_get_responses(_BASE))
        post = _fake_post_factory({
            f"{_BASE}/api/lab-sessions": (201, '{"id":"new-session"}'),
        })
        report = trial.run_trial(
            env_vars=_STAGING_ENV,
            base_url=_BASE,
            allow_runtime_start=True,
            staging_lab_draft_id="draft-id",
            http_get=get,
            http_post=post,
        )
        runtime_checks = [c for c in report.checks if c.phase == trial._PHASE_RUNTIME]
        assert any(c.severity == "pass" for c in runtime_checks)

    def test_runtime_start_422_adds_warning_not_blocking(self) -> None:
        get = _fake_get_factory(_make_happy_get_responses(_BASE))
        post = _fake_post_factory({
            f"{_BASE}/api/lab-sessions": (422, '{"detail":"preconditions not met"}'),
        })
        report = trial.run_trial(
            env_vars=_STAGING_ENV,
            base_url=_BASE,
            allow_runtime_start=True,
            staging_lab_draft_id="draft-id",
            http_get=get,
            http_post=post,
        )
        runtime_checks = [c for c in report.checks if c.phase == trial._PHASE_RUNTIME]
        severities = {c.severity for c in runtime_checks}
        assert "blocking" not in severities, "422 should be warning, not blocking"
        assert "warning" in severities

    def test_runtime_start_401_adds_blocking_check(self) -> None:
        get = _fake_get_factory(_make_happy_get_responses(_BASE))
        post = _fake_post_factory({
            f"{_BASE}/api/lab-sessions": (401, "Unauthorized"),
        })
        report = trial.run_trial(
            env_vars=_STAGING_ENV,
            base_url=_BASE,
            allow_runtime_start=True,
            staging_lab_draft_id="draft-id",
            http_get=get,
            http_post=post,
        )
        runtime_checks = [c for c in report.checks if c.phase == trial._PHASE_RUNTIME]
        assert any(c.severity == "blocking" for c in runtime_checks)

    def test_runtime_start_without_user_session_is_blocking_no_request(self) -> None:
        """No STAGING_USER_SESSION → blocking immediately, no HTTP request sent."""
        no_session_env = {**_STAGING_ENV, "STAGING_USER_SESSION": ""}
        get = _fake_get_factory(_make_happy_get_responses(_BASE))
        post = _fake_post_factory({})
        report = trial.run_trial(
            env_vars=no_session_env,
            base_url=_BASE,
            allow_runtime_start=True,
            staging_lab_draft_id="draft-id",
            http_get=get,
            http_post=post,
        )
        runtime_checks = [c for c in report.checks if c.phase == trial._PHASE_RUNTIME]
        assert any(c.severity == "blocking" for c in runtime_checks)
        # Must NOT have sent a POST request (fail closed before sending)
        session_posts = [url for url, _, _ in post.calls if "/api/lab-sessions" in url]
        assert len(session_posts) == 0, "Must not send POST when user_session is absent"


# ---------------------------------------------------------------------------
# D — Missing required args returns blocking failure
# ---------------------------------------------------------------------------


class TestMissingRequiredArgs:
    def test_runtime_start_without_base_url_is_blocking(self) -> None:
        report = trial.run_trial(
            env_vars=_STAGING_ENV,
            allow_runtime_start=True,
            staging_lab_draft_id="some-id",
        )
        runtime_checks = [c for c in report.checks if c.phase == trial._PHASE_RUNTIME]
        assert any(c.severity == "blocking" for c in runtime_checks)
        assert any("base-url" in c.message.lower() for c in runtime_checks)

    def test_runtime_start_without_lab_draft_id_is_blocking(self) -> None:
        get = _fake_get_factory(_make_happy_get_responses(_BASE))
        report = trial.run_trial(
            env_vars=_STAGING_ENV,
            base_url=_BASE,
            allow_runtime_start=True,
            staging_lab_draft_id=None,
            http_get=get,
        )
        runtime_checks = [c for c in report.checks if c.phase == trial._PHASE_RUNTIME]
        assert any(c.severity == "blocking" for c in runtime_checks)
        assert any("staging-lab-draft-id" in c.message.lower() for c in runtime_checks)

    def test_expiry_without_base_url_is_blocking(self) -> None:
        report = trial.run_trial(
            env_vars=_STAGING_ENV,
            allow_timeout_expiry=True,
        )
        expiry_checks = [c for c in report.checks if c.phase == trial._PHASE_EXPIRY]
        assert any(c.severity == "blocking" for c in expiry_checks)

    def test_cleanup_without_base_url_is_blocking(self) -> None:
        report = trial.run_trial(
            env_vars=_STAGING_ENV,
            allow_cleanup_check=True,
            staging_session_id="some-session",
        )
        cleanup_checks = [c for c in report.checks if c.phase == trial._PHASE_CLEANUP]
        assert any(c.severity == "blocking" for c in cleanup_checks)

    def test_cleanup_without_session_id_is_blocking(self) -> None:
        get = _fake_get_factory(_make_happy_get_responses(_BASE))
        report = trial.run_trial(
            env_vars=_STAGING_ENV,
            base_url=_BASE,
            allow_cleanup_check=True,
            staging_session_id=None,
            http_get=get,
        )
        cleanup_checks = [c for c in report.checks if c.phase == trial._PHASE_CLEANUP]
        assert any(c.severity == "blocking" for c in cleanup_checks)
        assert any("staging-session-id" in c.message.lower() for c in cleanup_checks)

    def test_missing_env_file_returns_blocking_report(self, tmp_path) -> None:
        report = trial.run_from_env_file(str(tmp_path / "nonexistent.env"))
        assert report.blocking_count() > 0
        assert report.overall == "blocking"


# ---------------------------------------------------------------------------
# E — Diagnostics secret leak detection
# ---------------------------------------------------------------------------


class TestDiagnosticsSecretLeak:
    def test_api_key_in_get_response_is_blocking(self) -> None:
        responses = {
            **_make_happy_get_responses(_BASE),
            f"{_BASE}/openapi.json": (200, '{"data":"sk-ant-abc123"}'),
        }
        get = _fake_get_factory(responses)
        report = trial.run_trial(env_vars=_STAGING_ENV, base_url=_BASE, http_get=get)
        leak_checks = [c for c in report.checks if "secret_leak" in c.name]
        assert len(leak_checks) > 0
        assert all(c.severity == "blocking" for c in leak_checks)

    def test_pem_key_in_get_response_is_blocking(self) -> None:
        responses = {
            **_make_happy_get_responses(_BASE),
            f"{_BASE}/api/labgen/contract-pack": (200, '{"content":"-----BEGIN PRIVATE KEY-----"}'),
        }
        get = _fake_get_factory(responses)
        report = trial.run_trial(env_vars=_STAGING_ENV, base_url=_BASE, http_get=get)
        leak_checks = [c for c in report.checks if "secret_leak" in c.name]
        assert len(leak_checks) > 0

    def test_post_response_secret_leak_is_blocking(self) -> None:
        get = _fake_get_factory(_make_happy_get_responses(_BASE))
        post = _fake_post_factory({
            f"{_BASE}/api/lab-sessions": (201, '{"id":"sid","key":"sk-ant-leaked"}'),
        })
        report = trial.run_trial(
            env_vars=_STAGING_ENV,
            base_url=_BASE,
            allow_runtime_start=True,
            staging_lab_draft_id="draft-id",
            http_get=get,
            http_post=post,
        )
        leak_checks = [c for c in report.checks if "secret_leak" in c.name]
        assert len(leak_checks) > 0
        assert all(c.severity == "blocking" for c in leak_checks)

    def test_clean_responses_no_leak_checks(self) -> None:
        get = _fake_get_factory(_make_happy_get_responses(_BASE))
        report = trial.run_trial(env_vars=_STAGING_ENV, base_url=_BASE, http_get=get)
        leak_checks = [c for c in report.checks if "secret_leak" in c.name]
        assert len(leak_checks) == 0


# ---------------------------------------------------------------------------
# F — Unsafe adapter status blocking gate
# ---------------------------------------------------------------------------


class TestUnsafeAdapterStatus:
    def test_production_safe_false_is_blocking(self) -> None:
        responses = {
            **_make_happy_get_responses(_BASE),
            f"{_BASE}/api/labgen/runtime/adapter-status": (
                200,
                '{"namespace_adapter_kind":"stub","production_safe":false,"runtime_mode":"production"}',
            ),
        }
        get = _fake_get_factory(responses)
        report = trial.run_trial(env_vars=_STAGING_ENV, base_url=_BASE, http_get=get)
        gate_checks = [c for c in report.checks if c.name == "adapter_safety_gate"]
        assert len(gate_checks) > 0
        assert any(c.severity == "blocking" for c in gate_checks)

    def test_stub_adapter_kind_is_blocking(self) -> None:
        responses = {
            **_make_happy_get_responses(_BASE),
            f"{_BASE}/api/labgen/runtime/adapter-status": (
                200,
                '{"namespace_adapter_kind":"stub","production_safe":true}',
            ),
        }
        get = _fake_get_factory(responses)
        report = trial.run_trial(env_vars=_STAGING_ENV, base_url=_BASE, http_get=get)
        gate_checks = [c for c in report.checks if c.name == "adapter_safety_gate"]
        assert any(c.severity == "blocking" for c in gate_checks)

    def test_production_safe_false_blocks_runtime_start(self) -> None:
        responses = {
            **_make_happy_get_responses(_BASE),
            f"{_BASE}/api/labgen/runtime/adapter-status": (
                200,
                '{"namespace_adapter_kind":"stub","production_safe":false}',
            ),
        }
        get = _fake_get_factory(responses)
        post = _fake_post_factory({})
        trial.run_trial(
            env_vars=_STAGING_ENV,
            base_url=_BASE,
            allow_runtime_start=True,
            staging_lab_draft_id="draft-id",
            http_get=get,
            http_post=post,
        )
        session_posts = [url for url, _, _ in post.calls if "/api/lab-sessions" in url]
        assert len(session_posts) == 0, "Runtime start must be skipped if adapter is unsafe"

    def test_k8s_adapter_production_safe_passes_gate(self) -> None:
        get = _fake_get_factory(_make_happy_get_responses(_BASE))
        report = trial.run_trial(env_vars=_STAGING_ENV, base_url=_BASE, http_get=get)
        gate_checks = [c for c in report.checks if c.name == "adapter_safety_gate"]
        if gate_checks:
            assert all(c.severity in ("pass", "warning") for c in gate_checks)

    def test_adapter_status_unreachable_blocks_runtime_start(self) -> None:
        """When adapter-status endpoint fails, metadata=None — whitelist gate blocks runtime start."""
        responses = {
            **_make_happy_get_responses(_BASE),
            f"{_BASE}/api/labgen/runtime/adapter-status": (500, "Internal Server Error"),
        }
        get = _fake_get_factory(responses)
        post = _fake_post_factory({})
        trial.run_trial(
            env_vars=_STAGING_ENV,
            base_url=_BASE,
            allow_runtime_start=True,
            staging_lab_draft_id="draft-id",
            http_get=get,
            http_post=post,
        )
        # Whitelist logic: adapter_production_safe=None (not True) → runtime start must NOT be called
        session_posts = [url for url, _, _ in post.calls if "/api/lab-sessions" in url]
        assert len(session_posts) == 0, \
            "Runtime start must be blocked when adapter-status is unreachable (whitelist gate)"

    def test_adapter_status_invalid_json_blocks_runtime_start(self) -> None:
        """Non-JSON adapter-status response → metadata=None → whitelist blocks runtime start."""
        responses = {
            **_make_happy_get_responses(_BASE),
            f"{_BASE}/api/labgen/runtime/adapter-status": (200, "not valid json {{{"),
        }
        get = _fake_get_factory(responses)
        post = _fake_post_factory({})
        trial.run_trial(
            env_vars=_STAGING_ENV,
            base_url=_BASE,
            allow_runtime_start=True,
            staging_lab_draft_id="draft-id",
            http_get=get,
            http_post=post,
        )
        session_posts = [url for url, _, _ in post.calls if "/api/lab-sessions" in url]
        assert len(session_posts) == 0, \
            "Runtime start must be blocked when adapter-status JSON is unparseable"


# ---------------------------------------------------------------------------
# G — LLM live-enabled blocking gate
# ---------------------------------------------------------------------------


class TestLLMLiveGate:
    def test_live_enabled_true_is_blocking(self) -> None:
        responses = {
            **_make_happy_get_responses(_BASE),
            f"{_BASE}/api/labgen/llm-provider/status": (200, '{"live_enabled":true}'),
        }
        get = _fake_get_factory(responses)
        report = trial.run_trial(env_vars=_STAGING_ENV, base_url=_BASE, http_get=get)
        llm_checks = [c for c in report.checks if c.name == "llm_live_gate"]
        assert any(c.severity == "blocking" for c in llm_checks)

    def test_live_enabled_true_blocks_runtime_start(self) -> None:
        responses = {
            **_make_happy_get_responses(_BASE),
            f"{_BASE}/api/labgen/llm-provider/status": (200, '{"live_enabled":true}'),
        }
        get = _fake_get_factory(responses)
        post = _fake_post_factory({})
        trial.run_trial(
            env_vars=_STAGING_ENV,
            base_url=_BASE,
            allow_runtime_start=True,
            staging_lab_draft_id="draft-id",
            http_get=get,
            http_post=post,
        )
        session_posts = [url for url, _, _ in post.calls if "/api/lab-sessions" in url]
        assert len(session_posts) == 0, "Runtime start must be skipped if LLM is live"

    def test_live_enabled_false_passes_gate(self) -> None:
        get = _fake_get_factory(_make_happy_get_responses(_BASE))
        report = trial.run_trial(env_vars=_STAGING_ENV, base_url=_BASE, http_get=get)
        llm_checks = [c for c in report.checks if c.name == "llm_live_gate"]
        if llm_checks:
            assert all(c.severity in ("pass", "warning") for c in llm_checks)


# ---------------------------------------------------------------------------
# H — JSON output schema stability
# ---------------------------------------------------------------------------


class TestJSONOutputSchema:
    def _get_json(self, env: dict) -> dict:
        report = trial.run_trial(env_vars=env)
        buf = StringIO()
        with patch("sys.stdout", buf):
            trial._json_output(report, "diagnostics_only")
        return json.loads(buf.getvalue())

    def test_required_top_level_keys(self) -> None:
        out = self._get_json(_STAGING_ENV)
        for key in ("tool", "execution_mode", "overall", "pass_count",
                    "warning_count", "blocking_count", "phases", "checks"):
            assert key in out, f"Missing top-level key: {key!r}"

    def test_tool_field_value(self) -> None:
        out = self._get_json(_STAGING_ENV)
        assert out["tool"] == "labgen_controlled_staging_trial"

    def test_overall_is_valid_enum(self) -> None:
        out = self._get_json(_STAGING_ENV)
        assert out["overall"] in ("pass", "warning", "blocking")

    def test_counts_are_non_negative_ints(self) -> None:
        out = self._get_json(_STAGING_ENV)
        for k in ("pass_count", "warning_count", "blocking_count"):
            assert isinstance(out[k], int) and out[k] >= 0

    def test_each_check_has_required_fields(self) -> None:
        out = self._get_json(_STAGING_ENV)
        for check in out["checks"]:
            assert "phase" in check
            assert "name" in check
            assert "severity" in check
            assert "message" in check

    def test_severity_values_are_valid(self) -> None:
        out = self._get_json(_STAGING_ENV)
        for check in out["checks"]:
            assert check["severity"] in ("pass", "warning", "blocking")

    def test_schema_stable_across_runs(self) -> None:
        out1 = self._get_json(_STAGING_ENV)
        out2 = self._get_json(_STAGING_ENV)
        assert sorted(out1.keys()) == sorted(out2.keys())

    def test_execution_mode_diagnostics_only_when_no_flags(self) -> None:
        report = trial.run_trial(env_vars=_STAGING_ENV)
        buf = StringIO()
        with patch("sys.stdout", buf):
            trial._json_output(report, "diagnostics_only")
        out = json.loads(buf.getvalue())
        assert out["execution_mode"] == "diagnostics_only"


# ---------------------------------------------------------------------------
# I — HTTP client injection (GET + POST)
# ---------------------------------------------------------------------------


class TestHTTPClientInjection:
    def test_get_client_fully_injectable(self) -> None:
        get_calls: list[str] = []

        def custom_get(url, headers):
            get_calls.append(url)
            if "contract-pack" in url:
                return 200, '{"version":"v0.1","endpoints":[]}', None
            if "adapter-status" in url:
                return 200, '{"namespace_adapter_kind":"k8s","production_safe":true}', None
            if "llm-provider" in url:
                return 200, '{"live_enabled":false}', None
            return 200, "{}", None

        trial.run_trial(env_vars=_STAGING_ENV, base_url=_BASE, http_get=custom_get)
        assert len(get_calls) > 0, "Custom GET client must be called"

    def test_post_client_fully_injectable(self) -> None:
        get = _fake_get_factory(_make_happy_get_responses(_BASE))
        post_calls: list[tuple] = []

        def custom_post(url, headers, body):
            post_calls.append((url, headers, body))
            return 201, '{"id":"injected-session"}', None

        trial.run_trial(
            env_vars=_STAGING_ENV,
            base_url=_BASE,
            allow_runtime_start=True,
            staging_lab_draft_id="draft-id",
            http_get=get,
            http_post=custom_post,
        )
        assert any("/api/lab-sessions" in url for url, _, _ in post_calls)

    def test_no_real_network_in_offline_mode(self) -> None:
        called: list[str] = []

        def asserting_get(url, headers):
            called.append(url)
            raise AssertionError(f"No HTTP calls allowed in offline mode, but got: {url}")

        def asserting_post(url, headers, body):
            raise AssertionError(f"No POST calls allowed in offline mode, but got: {url}")

        # No base_url → should not call either client
        trial.run_trial(
            env_vars=_STAGING_ENV,
            http_get=asserting_get,
            http_post=asserting_post,
        )
        assert len(called) == 0


# ---------------------------------------------------------------------------
# J — Expiry phase
# ---------------------------------------------------------------------------


class TestExpiryPhase:
    def test_expiry_flag_posts_to_expire_sessions(self) -> None:
        get = _fake_get_factory(_make_happy_get_responses(_BASE))
        post = _fake_post_factory({
            f"{_BASE}/api/labgen/runtime/expire-sessions": (200, '{"expired":[]}'),
        })
        trial.run_trial(
            env_vars=_STAGING_ENV,
            base_url=_BASE,
            allow_timeout_expiry=True,
            http_get=get,
            http_post=post,
        )
        expiry_posts = [
            url for url, _, _ in post.calls
            if "expire-sessions" in url
        ]
        assert len(expiry_posts) == 1

    def test_expiry_posts_dry_run_true(self) -> None:
        get = _fake_get_factory(_make_happy_get_responses(_BASE))
        post = _fake_post_factory({
            f"{_BASE}/api/labgen/runtime/expire-sessions": (200, "{}"),
        })
        trial.run_trial(
            env_vars=_STAGING_ENV,
            base_url=_BASE,
            allow_timeout_expiry=True,
            http_get=get,
            http_post=post,
        )
        for url, _, body in post.calls:
            if "expire-sessions" in url:
                assert body.get("dry_run") is True, "Expiry must use dry_run=True"

    def test_expiry_200_adds_pass_check(self) -> None:
        get = _fake_get_factory(_make_happy_get_responses(_BASE))
        post = _fake_post_factory({
            f"{_BASE}/api/labgen/runtime/expire-sessions": (200, '{"expired":[],"cleaned":[]}'),
        })
        report = trial.run_trial(
            env_vars=_STAGING_ENV,
            base_url=_BASE,
            allow_timeout_expiry=True,
            http_get=get,
            http_post=post,
        )
        expiry_checks = [c for c in report.checks if c.phase == trial._PHASE_EXPIRY]
        assert any(c.severity == "pass" for c in expiry_checks)

    def test_expiry_401_adds_blocking_check(self) -> None:
        get = _fake_get_factory(_make_happy_get_responses(_BASE))
        post = _fake_post_factory({
            f"{_BASE}/api/labgen/runtime/expire-sessions": (401, "Unauthorized"),
        })
        report = trial.run_trial(
            env_vars=_STAGING_ENV,
            base_url=_BASE,
            allow_timeout_expiry=True,
            http_get=get,
            http_post=post,
        )
        expiry_checks = [c for c in report.checks if c.phase == trial._PHASE_EXPIRY]
        assert any(c.severity == "blocking" for c in expiry_checks)


# ---------------------------------------------------------------------------
# K — Cleanup phase
# ---------------------------------------------------------------------------


class TestCleanupPhase:
    def test_cleanup_flag_posts_to_complete(self) -> None:
        get = _fake_get_factory(_make_happy_get_responses(_BASE))
        post = _fake_post_factory({
            f"{_BASE}/api/lab-sessions/my-session-id/complete": (200, "{}"),
        })
        trial.run_trial(
            env_vars=_STAGING_ENV,
            base_url=_BASE,
            allow_cleanup_check=True,
            staging_session_id="my-session-id",
            http_get=get,
            http_post=post,
        )
        complete_posts = [
            url for url, _, _ in post.calls
            if "/complete" in url
        ]
        assert len(complete_posts) == 1

    def test_cleanup_200_adds_pass_check(self) -> None:
        get = _fake_get_factory(_make_happy_get_responses(_BASE))
        post = _fake_post_factory({
            f"{_BASE}/api/lab-sessions/sid/complete": (200, "{}"),
        })
        report = trial.run_trial(
            env_vars=_STAGING_ENV,
            base_url=_BASE,
            allow_cleanup_check=True,
            staging_session_id="sid",
            http_get=get,
            http_post=post,
        )
        cleanup_checks = [c for c in report.checks if c.phase == trial._PHASE_CLEANUP]
        assert any(c.severity == "pass" for c in cleanup_checks)

    def test_cleanup_409_adds_warning(self) -> None:
        get = _fake_get_factory(_make_happy_get_responses(_BASE))
        post = _fake_post_factory({
            f"{_BASE}/api/lab-sessions/sid/complete": (409, '{"detail":"not ready"}'),
        })
        report = trial.run_trial(
            env_vars=_STAGING_ENV,
            base_url=_BASE,
            allow_cleanup_check=True,
            staging_session_id="sid",
            http_get=get,
            http_post=post,
        )
        cleanup_checks = [c for c in report.checks if c.phase == trial._PHASE_CLEANUP]
        assert any(c.severity == "warning" for c in cleanup_checks)

    def test_cleanup_uses_runtime_session_id_if_no_staging_id(self) -> None:
        get = _fake_get_factory(_make_happy_get_responses(_BASE))
        post = _fake_post_factory({
            f"{_BASE}/api/lab-sessions": (201, '{"id":"runtime-created-session"}'),
            f"{_BASE}/api/lab-sessions/runtime-created-session/complete": (200, "{}"),
        })
        report = trial.run_trial(
            env_vars=_STAGING_ENV,
            base_url=_BASE,
            allow_runtime_start=True,
            allow_cleanup_check=True,
            staging_lab_draft_id="draft-id",
            staging_session_id=None,
            http_get=get,
            http_post=post,
        )
        cleanup_checks = [c for c in report.checks if c.phase == trial._PHASE_CLEANUP]
        # Should either pass or warn (not "blocked: no session id")
        blocking_no_session = [
            c for c in cleanup_checks
            if c.severity == "blocking" and "staging-session-id" in c.message.lower()
        ]
        assert len(blocking_no_session) == 0, \
            "Should use runtime-created session ID when staging_session_id is None"


# ---------------------------------------------------------------------------
# L — No secret values printed
# ---------------------------------------------------------------------------


class TestNoSecretsPrinted:
    _SECRET_VALUES = [
        "staging-token-secret-value",
        "staging-vm-password",
        "a" * 36,
        "staging-session-cookie-value",
    ]

    def test_no_secret_values_in_human_output(self) -> None:
        report = trial.run_trial(env_vars=_STAGING_ENV)
        buf = StringIO()
        with patch("sys.stdout", buf):
            trial._human_output(report, "diagnostics_only")
        output = buf.getvalue()
        for secret in self._SECRET_VALUES:
            assert secret not in output, f"Secret value found in human output: {secret[:8]}..."

    def test_no_secret_values_in_json_output(self) -> None:
        report = trial.run_trial(env_vars=_STAGING_ENV)
        buf = StringIO()
        with patch("sys.stdout", buf):
            trial._json_output(report, "diagnostics_only")
        output = buf.getvalue()
        for secret in self._SECRET_VALUES:
            assert secret not in output, f"Secret value found in JSON output: {secret[:8]}..."

    def test_no_sensitive_patterns_in_any_output(self) -> None:
        report = trial.run_trial(env_vars=_STAGING_ENV)
        output = _all_output(report)
        for pat in ("sk-ant-", "sk-proj-", "-----BEGIN", "client-certificate-data:"):
            assert pat not in output, f"Sensitive pattern in output: {pat!r}"


# ---------------------------------------------------------------------------
# M — Env context restores original environment
# ---------------------------------------------------------------------------


class TestEnvContextIntegration:
    def test_env_context_restored_after_trial(self) -> None:
        original = os.environ.get("LABGEN_RUNTIME_MODE", "_NOT_SET_")
        trial.run_trial(env_vars={"LABGEN_RUNTIME_MODE": "test_isolation_check"})
        restored = os.environ.get("LABGEN_RUNTIME_MODE", "_NOT_SET_")
        assert restored == original, "env_context must restore original environment"

    def test_valid_env_file_loads_and_runs_preflight(self, tmp_path) -> None:
        env_file = tmp_path / "staging.env"
        lines = "\n".join(f"{k}={v}" for k, v in _STAGING_ENV.items())
        env_file.write_text(lines + "\n")
        report = trial.run_from_env_file(str(env_file))
        preflight = [c for c in report.checks if c.phase == trial._PHASE_PREFLIGHT]
        assert len(preflight) > 0

    def test_stub_adapter_in_env_propagates_blocking(self) -> None:
        bad_env = {**_STAGING_ENV, "LABGEN_NAMESPACE_ADAPTER": "stub"}
        report = trial.run_trial(env_vars=bad_env)
        assert report.blocking_count() > 0
