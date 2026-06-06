"""HTTP integration tests for /api/deployments/* routes."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.deployments_routes import router, DEPLOYMENT_CASES


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def deploy_setup(tmp_path):
    """TestClient with DEPLOYMENTS_DIR pointing to tmp_path.

    Creates a real markdown file for D01 only.
    Other cases are absent to test 404 paths separately.
    """
    dep_dir = tmp_path / "deployments"
    dep_dir.mkdir()

    (dep_dir / "D01-guestbook.md").write_text("# 案例 D01\n内容", encoding="utf-8")

    app = FastAPI()
    app.include_router(router)

    with patch("backend.deployments_routes.DEPLOYMENTS_DIR", dep_dir):
        yield TestClient(app, raise_server_exceptions=True)


# ============================================================
# GET /api/deployments
# ============================================================

class TestListDeployments:
    def test_returns_all_cases(self, deploy_setup):
        resp = deploy_setup.get("/api/deployments")
        assert resp.status_code == 200
        cases = resp.json()["deployments"]
        assert len(cases) == len(DEPLOYMENT_CASES)

    def test_each_case_has_required_fields(self, deploy_setup):
        resp = deploy_setup.get("/api/deployments")
        for case in resp.json()["deployments"]:
            assert "id" in case
            assert "title" in case
            assert "difficulty" in case
            assert "duration" in case
            assert "phase" in case

    def test_ids_use_d_prefix(self, deploy_setup):
        resp = deploy_setup.get("/api/deployments")
        ids = [c["id"] for c in resp.json()["deployments"]]
        assert all(cid.startswith("D") for cid in ids)

    def test_no_auth_required(self, deploy_setup):
        resp = deploy_setup.get("/api/deployments")
        assert resp.status_code == 200


# ============================================================
# GET /api/deployments/{case_id}
# ============================================================

class TestGetDeployment:
    def test_valid_id_returns_content(self, deploy_setup):
        resp = deploy_setup.get("/api/deployments/D01")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "D01"
        assert "content" in data
        assert len(data["content"]) > 0

    def test_response_includes_metadata(self, deploy_setup):
        resp = deploy_setup.get("/api/deployments/D01")
        data = resp.json()
        assert "title" in data
        assert "difficulty" in data
        assert "duration" in data

    def test_unknown_id_returns_404(self, deploy_setup):
        resp = deploy_setup.get("/api/deployments/D99")
        assert resp.status_code == 404

    def test_invalid_id_format_returns_404(self, deploy_setup):
        resp = deploy_setup.get("/api/deployments/invalid")
        assert resp.status_code == 404

    def test_missing_file_returns_404(self, deploy_setup):
        """Known case ID but the file hasn't been created yet."""
        resp = deploy_setup.get("/api/deployments/D02")
        assert resp.status_code == 404

    def test_id_is_case_sensitive(self, deploy_setup):
        resp = deploy_setup.get("/api/deployments/d01")
        assert resp.status_code == 404

    def test_oversized_id_returns_404(self, deploy_setup):
        resp = deploy_setup.get("/api/deployments/" + "A" * 21)
        assert resp.status_code == 404

    def test_session_token_triggers_activity_update(self, deploy_setup):
        with patch("backend.deployments_routes.auth_manager") as mock_am:
            resp = deploy_setup.get(
                "/api/deployments/D01",
                cookies={"session_token": "tok123"},
            )
            assert resp.status_code == 200
            mock_am.update_session_activity.assert_called_once_with("tok123", current_experiment="D01")

    def test_activity_update_exception_is_swallowed(self, deploy_setup):
        with patch("backend.deployments_routes.auth_manager") as mock_am:
            mock_am.update_session_activity.side_effect = Exception("disk full")
            resp = deploy_setup.get(
                "/api/deployments/D01",
                cookies={"session_token": "tok"},
            )
            assert resp.status_code == 200
