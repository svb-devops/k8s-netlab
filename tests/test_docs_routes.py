"""HTTP integration tests for /api/experiments/* routes."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.docs_routes import router, EXPERIMENTS


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def docs_setup(tmp_path):
    """TestClient with EXPERIMENTS_DIR pointing to tmp_path.

    Creates a real markdown file for experiment "01" only.
    All other experiments are absent (test 404 paths separately).
    """
    exp_dir = tmp_path / "experiments"
    exp_dir.mkdir()

    # Create files for first two experiments
    (exp_dir / "01-kubernetes-network-basics.md").write_text("# 实验一\n内容", encoding="utf-8")
    (exp_dir / "02-pod-network-deep-dive.md").write_text("# 实验二\n内容", encoding="utf-8")

    app = FastAPI()
    app.include_router(router)

    with patch("backend.docs_routes.EXPERIMENTS_DIR", exp_dir):
        yield TestClient(app, raise_server_exceptions=True)


# ============================================================
# GET /api/experiments
# ============================================================

class TestListExperiments:
    def test_returns_all_experiments(self, docs_setup):
        client = docs_setup
        resp = client.get("/api/experiments")
        assert resp.status_code == 200
        experiments = resp.json()["experiments"]
        assert len(experiments) == len(EXPERIMENTS)

    def test_each_experiment_has_required_fields(self, docs_setup):
        client = docs_setup
        resp = client.get("/api/experiments")
        for exp in resp.json()["experiments"]:
            assert "id" in exp
            assert "title" in exp
            assert "difficulty" in exp
            assert "duration" in exp
            assert "phase" in exp

    def test_ids_are_sequential(self, docs_setup):
        client = docs_setup
        resp = client.get("/api/experiments")
        ids = [e["id"] for e in resp.json()["experiments"]]
        assert ids == [f"{i:02d}" for i in range(1, len(EXPERIMENTS) + 1)]

    def test_no_auth_required(self, docs_setup):
        """Experiment list is public — no cookie needed."""
        client = docs_setup
        resp = client.get("/api/experiments")
        assert resp.status_code == 200


# ============================================================
# GET /api/experiments/{exp_id}
# ============================================================

class TestGetExperiment:
    def test_valid_id_returns_content(self, docs_setup):
        client = docs_setup
        resp = client.get("/api/experiments/01")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "01"
        assert data["title"] == "Kubernetes 网络基础"
        assert "content" in data
        assert len(data["content"]) > 0

    def test_response_includes_metadata(self, docs_setup):
        client = docs_setup
        resp = client.get("/api/experiments/01")
        data = resp.json()
        assert "difficulty" in data
        assert "duration" in data

    def test_unknown_id_returns_404(self, docs_setup):
        client = docs_setup
        resp = client.get("/api/experiments/99")
        assert resp.status_code == 404

    def test_missing_file_returns_404(self, docs_setup):
        """Experiment registered in metadata but file not on disk → 404."""
        client = docs_setup
        # "03" is in EXPERIMENTS but not created in tmp_path
        resp = client.get("/api/experiments/03")
        assert resp.status_code == 404

    def test_no_auth_required(self, docs_setup):
        client = docs_setup
        resp = client.get("/api/experiments/01")
        assert resp.status_code == 200

    def test_with_valid_session_updates_activity(self, docs_setup):
        """When session_token cookie is present, activity must be updated."""
        client = docs_setup
        mock_auth = MagicMock()
        with patch("backend.docs_routes.auth_manager", mock_auth):
            client.cookies.set("session_token", "valid-token")
            resp = client.get("/api/experiments/01")

        assert resp.status_code == 200
        mock_auth.update_session_activity.assert_called_once_with("valid-token", current_experiment="01")

    def test_without_session_skips_activity_update(self, docs_setup):
        """No cookie → activity update must not be called."""
        client = docs_setup
        mock_auth = MagicMock()
        with patch("backend.docs_routes.auth_manager", mock_auth):
            resp = client.get("/api/experiments/02")

        assert resp.status_code == 200
        mock_auth.update_session_activity.assert_not_called()

    def test_path_traversal_via_malicious_filename_is_blocked(self, tmp_path):
        """路径遍历防御：伪造含 '..' 的 filename 不得读取实验目录外的文件（K 回归）。"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend.docs_routes import router

        exp_dir = tmp_path / "experiments"
        exp_dir.mkdir()
        secret_file = tmp_path / "secret.txt"
        secret_file.write_text("TOP_SECRET_CONTENT", encoding="utf-8")

        evil_exp = [{
            "id": "99", "filename": "../secret.txt",
            "title": "X", "difficulty": 1, "duration": "0", "phase": 1,
        }]

        app = FastAPI()
        app.include_router(router)

        with patch("backend.docs_routes.EXPERIMENTS_DIR", exp_dir), \
             patch("backend.docs_routes.EXPERIMENTS", evil_exp):
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.get("/api/experiments/99")

        assert resp.status_code == 404
        assert "TOP_SECRET_CONTENT" not in resp.text
