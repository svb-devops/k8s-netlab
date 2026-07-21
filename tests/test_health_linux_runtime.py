"""
Regression tests for the /api/health `linux_runtime` block.

Purpose: surface labgen-linux-runner misconfiguration (deleted account, wrong
LABGEN_LINUX_RUNNER_USER, resolution failure) in health instead of letting it
silently disable the Linux domain or, worse, silently fall back to root
execution. UID/GID are deliberately not treated as secrets here.
"""

import pytest

from backend import api_routes, config

pytestmark = pytest.mark.static


@pytest.fixture(autouse=True)
def _reset_linux_runtime_singleton(monkeypatch):
    from backend.labgen import routes as labgen_routes

    monkeypatch.setattr(labgen_routes, "_linux_runtime_adapter", None)
    monkeypatch.setattr(labgen_routes, "_linux_runtime_identity_error", None)
    yield
    monkeypatch.setattr(labgen_routes, "_linux_runtime_adapter", None)
    monkeypatch.setattr(labgen_routes, "_linux_runtime_identity_error", None)


class TestLinuxRuntimeHealthCheck:

    def test_disabled_by_default_reports_enabled_false(self, monkeypatch):
        monkeypatch.setattr(config, "LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS", frozenset())
        result = api_routes._check_linux_runtime_health()
        assert result["enabled"] is False
        assert result["runner_ready"] is None

    def test_enabled_with_valid_runner_reports_ready(self, monkeypatch):
        monkeypatch.setattr(config, "LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS", frozenset({"some-lab"}))
        monkeypatch.setattr(config, "LABGEN_LINUX_RUNNER_USER", "labgen-linux-runner")
        monkeypatch.setattr(config, "LABGEN_LINUX_RUNNER_GROUP", "labgen-linux-runner")

        result = api_routes._check_linux_runtime_health()

        assert result["enabled"] is True
        assert result["runner_ready"] is True
        assert result["runner_is_root"] is False
        assert result["runner_uid"] not in (0, None)
        assert result["runner_gid"] not in (0, None)

    def test_enabled_with_broken_runner_reports_not_ready_with_error(self, monkeypatch):
        monkeypatch.setattr(config, "LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS", frozenset({"some-lab"}))
        monkeypatch.setattr(config, "LABGEN_LINUX_RUNNER_USER", "definitely-not-real-xyz")

        result = api_routes._check_linux_runtime_health()

        assert result["enabled"] is True
        assert result["runner_ready"] is False
        assert result["runner_uid"] is None
        assert "error" in result

    def test_health_endpoint_includes_linux_runtime_block(self, monkeypatch):
        from fastapi.testclient import TestClient
        from backend.main import app

        monkeypatch.setattr(config, "LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS", frozenset())
        client = TestClient(app)
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert "linux_runtime" in body
        assert body["linux_runtime"]["enabled"] is False
