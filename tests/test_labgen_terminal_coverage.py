"""
Terminal module coverage补充测试。

Covers:
  A. kubectl_executor.execute() — async subprocess paths
  B. learner_credentials — K8s API functions (mocked)
  C. lab_kubectl_ws — WebSocket command loop paths
  D. lab_session_repository — update/delete/list methods
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from backend.labgen.kubectl_executor import CommandResult, execute
from backend.labgen.models import LabSessionState, LabSessionStatus

pytestmark = pytest.mark.static


# ═══════════════════════════════════════════════════════════════════════════════
# A. kubectl_executor.execute() — async subprocess paths
# ═══════════════════════════════════════════════════════════════════════════════

class TestExecuteBlocked:
    """execute() with a blocked command returns CommandResult(allowed=False)."""

    async def test_blocked_returns_not_allowed(self):
        result = await execute(
            "kubectl config view", "/fake/kc", "lab-ns", "sid-1", "learner"
        )
        assert not result.allowed
        assert result.block_reason
        assert result.exit_code == 1
        assert result.output == ""

    async def test_empty_command_returns_allowed_empty(self):
        result = await execute("", "/fake/kc", "lab-ns", "sid-1", "learner")
        assert result.allowed
        assert result.output == ""
        assert result.exit_code == 0

    async def test_whitespace_command_returns_allowed_empty(self):
        result = await execute("   ", "/fake/kc", "lab-ns", "sid-1", "learner")
        assert result.allowed
        assert result.exit_code == 0


class TestExecuteSubprocess:
    """execute() with mocked subprocess for the actual execution paths."""

    def _mock_proc(self, stdout: bytes, returncode: int = 0):
        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(stdout, None))
        proc.returncode = returncode
        proc.kill = MagicMock()
        proc.wait = AsyncMock()
        return proc

    async def test_successful_command_returns_output(self):
        proc = self._mock_proc(b"NAME              DATA\nmy-app-config   2\n")
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await execute(
                "kubectl get configmap my-app-config",
                "/fake/kc", "lab-ns", "sid", "learner",
            )
        assert result.allowed
        assert result.exit_code == 0
        assert "my-app-config" in result.output

    async def test_non_zero_exit_code_preserved(self):
        proc = self._mock_proc(b"Error from server: not found\n", returncode=1)
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await execute(
                "kubectl get configmap no-such-cm",
                "/fake/kc", "lab-ns", "sid", "learner",
            )
        assert result.allowed
        assert result.exit_code == 1
        assert "not found" in result.output

    async def test_output_truncated_at_64kb(self):
        large = b"x" * (65 * 1024)
        proc = self._mock_proc(large)
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await execute(
                "kubectl get pods", "/fake/kc", "lab-ns", "sid", "learner"
            )
        assert result.allowed
        assert "[output truncated]" in result.output
        assert len(result.output.encode()) < len(large)

    async def test_timeout_returns_124(self):
        proc = MagicMock()
        proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
        proc.kill = MagicMock()
        proc.wait = AsyncMock()
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await execute(
                "kubectl get pods", "/fake/kc", "lab-ns", "sid", "learner",
                timeout_seconds=1,
            )
        assert result.allowed
        assert result.exit_code == 124
        assert "timed out" in result.output

    async def test_file_not_found_returns_127(self):
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError()):
            result = await execute(
                "kubectl get pods", "/fake/kc", "lab-ns", "sid", "learner"
            )
        assert result.allowed
        assert result.exit_code == 127
        assert "not found" in result.output

    async def test_general_exception_returns_exit_1(self):
        with patch("asyncio.create_subprocess_exec", side_effect=RuntimeError("boom")):
            result = await execute(
                "kubectl get pods", "/fake/kc", "lab-ns", "sid", "learner"
            )
        assert result.allowed
        assert result.exit_code == 1
        assert "boom" in result.output


# ═══════════════════════════════════════════════════════════════════════════════
# B. learner_credentials — K8s API functions
# ═══════════════════════════════════════════════════════════════════════════════

class TestEnsureSa:
    def test_creates_sa_on_success(self):
        from backend.labgen.learner_credentials import _ensure_sa
        mock_core = MagicMock()
        _ensure_sa(mock_core, "lab-test-ns")
        mock_core.create_namespaced_service_account.assert_called_once()

    def test_ignores_409_conflict(self):
        from backend.labgen.learner_credentials import _ensure_sa
        from kubernetes.client.exceptions import ApiException
        mock_core = MagicMock()
        mock_core.create_namespaced_service_account.side_effect = ApiException(status=409)
        _ensure_sa(mock_core, "lab-ns")  # must not raise

    def test_propagates_non_409_error(self):
        from backend.labgen.learner_credentials import _ensure_sa
        from kubernetes.client.exceptions import ApiException
        mock_core = MagicMock()
        mock_core.create_namespaced_service_account.side_effect = ApiException(status=500)
        with pytest.raises(ApiException):
            _ensure_sa(mock_core, "lab-ns")


class TestEnsureRole:
    def test_creates_role_on_success(self):
        from backend.labgen.learner_credentials import _ensure_role
        mock_rbac = MagicMock()
        _ensure_role(mock_rbac, "lab-ns")
        mock_rbac.create_namespaced_role.assert_called_once()

    def test_ignores_409_conflict(self):
        from backend.labgen.learner_credentials import _ensure_role
        from kubernetes.client.exceptions import ApiException
        mock_rbac = MagicMock()
        mock_rbac.create_namespaced_role.side_effect = ApiException(status=409)
        _ensure_role(mock_rbac, "lab-ns")

    def test_propagates_non_409_error(self):
        from backend.labgen.learner_credentials import _ensure_role
        from kubernetes.client.exceptions import ApiException
        mock_rbac = MagicMock()
        mock_rbac.create_namespaced_role.side_effect = ApiException(status=403)
        with pytest.raises(ApiException):
            _ensure_role(mock_rbac, "lab-ns")


class TestEnsureRoleBinding:
    def test_creates_rolebinding_on_success(self):
        from backend.labgen.learner_credentials import _ensure_rolebinding
        mock_rbac = MagicMock()
        _ensure_rolebinding(mock_rbac, "lab-ns")
        mock_rbac.create_namespaced_role_binding.assert_called_once()

    def test_ignores_409_conflict(self):
        from backend.labgen.learner_credentials import _ensure_rolebinding
        from kubernetes.client.exceptions import ApiException
        mock_rbac = MagicMock()
        mock_rbac.create_namespaced_role_binding.side_effect = ApiException(status=409)
        _ensure_rolebinding(mock_rbac, "lab-ns")

    def test_propagates_non_409_error(self):
        from backend.labgen.learner_credentials import _ensure_rolebinding
        from kubernetes.client.exceptions import ApiException
        mock_rbac = MagicMock()
        mock_rbac.create_namespaced_role_binding.side_effect = ApiException(status=422)
        with pytest.raises(ApiException):
            _ensure_rolebinding(mock_rbac, "lab-ns")


class TestCreateSaToken:
    def test_returns_token_string(self):
        from backend.labgen.learner_credentials import _create_sa_token
        mock_core = MagicMock()
        mock_core.create_namespaced_service_account_token.return_value = MagicMock(
            status=MagicMock(token="eyJmYWtlLXRva2Vu")
        )
        token = _create_sa_token(mock_core, "lab-ns")
        assert token == "eyJmYWtlLXRva2Vu"

    def test_propagates_api_error(self):
        from backend.labgen.learner_credentials import _create_sa_token
        from kubernetes.client.exceptions import ApiException
        mock_core = MagicMock()
        mock_core.create_namespaced_service_account_token.side_effect = ApiException(status=503)
        with pytest.raises(ApiException):
            _create_sa_token(mock_core, "lab-ns")


class TestWriteKubeconfig:
    def test_writes_file_with_correct_permissions(self, tmp_path, monkeypatch):
        from backend.labgen import learner_credentials as lc

        monkeypatch.setattr(lc, "_CRED_BASE_DIR", tmp_path)

        platform_cfg = {
            "clusters": [
                {
                    "cluster": {
                        "server": "https://k3s.internal:6443",
                        "certificate-authority-data": "ZmFrZS1jYQ==",
                    }
                }
            ]
        }
        kc_file = tmp_path / "platform.kubeconfig"
        kc_file.write_text(yaml.dump(platform_cfg))

        sid = str(uuid.uuid4())
        path = lc._write_kubeconfig(sid, "lab-ns", "my-token-xyz", str(kc_file))

        assert path.exists()
        assert oct(path.stat().st_mode & 0o777) == oct(0o600)

    def test_kubeconfig_contains_server_and_token(self, tmp_path, monkeypatch):
        from backend.labgen import learner_credentials as lc

        monkeypatch.setattr(lc, "_CRED_BASE_DIR", tmp_path)
        platform_cfg = {
            "clusters": [
                {
                    "cluster": {
                        "server": "https://k3s.internal:6443",
                        "certificate-authority-data": "ZmFrZS1jYQ==",
                    }
                }
            ]
        }
        kc_file = tmp_path / "platform.kubeconfig"
        kc_file.write_text(yaml.dump(platform_cfg))

        sid = str(uuid.uuid4())
        path = lc._write_kubeconfig(sid, "lab-ns", "secret-token-abc", str(kc_file))

        content = yaml.safe_load(path.read_text())
        assert content["clusters"][0]["cluster"]["server"] == "https://k3s.internal:6443"
        assert content["users"][0]["user"]["token"] == "secret-token-abc"
        assert content["contexts"][0]["context"]["namespace"] == "lab-ns"


class TestEnsureLearnerCredentials:
    def test_full_flow_returns_path(self, tmp_path, monkeypatch):
        from backend.labgen import learner_credentials as lc
        from kubernetes import client as k8s_client

        cred_base = tmp_path / "creds"
        monkeypatch.setattr(lc, "_CRED_BASE_DIR", cred_base)

        platform_cfg = {
            "clusters": [
                {
                    "cluster": {
                        "server": "https://k3s.internal:6443",
                        "certificate-authority-data": "ZmFrZS1jYQ==",
                    }
                }
            ]
        }
        kc_file = tmp_path / "platform.kubeconfig"
        kc_file.write_text(yaml.dump(platform_cfg))

        mock_core = MagicMock()
        mock_core.create_namespaced_service_account.return_value = MagicMock()
        mock_core.create_namespaced_service_account_token.return_value = MagicMock(
            status=MagicMock(token="test-token")
        )
        mock_rbac = MagicMock()

        with (
            patch.object(lc, "_build_api_client", return_value=MagicMock()),
            patch.object(k8s_client, "CoreV1Api", return_value=mock_core),
            patch.object(k8s_client, "RbacAuthorizationV1Api", return_value=mock_rbac),
        ):
            sid = str(uuid.uuid4())
            path_str = lc.ensure_learner_credentials(sid, "lab-ns", str(kc_file))

        assert path_str.endswith("config")
        assert Path(path_str).exists()

    def test_invalid_session_id_raises(self):
        from backend.labgen import learner_credentials as lc

        with pytest.raises(ValueError, match="UUID"):
            lc.ensure_learner_credentials("bad-id", "lab-ns", "/fake/kc")


class TestReclaimLearnerCredentials:
    def test_ignores_404_on_k8s_objects(self, tmp_path, monkeypatch):
        from backend.labgen import learner_credentials as lc
        from kubernetes import client as k8s_client
        from kubernetes.client.exceptions import ApiException

        mock_core = MagicMock()
        mock_core.delete_namespaced_service_account.side_effect = ApiException(status=404)
        mock_rbac = MagicMock()
        mock_rbac.delete_namespaced_role.side_effect = ApiException(status=404)
        mock_rbac.delete_namespaced_role_binding.side_effect = ApiException(status=404)

        monkeypatch.setattr(lc, "_CRED_BASE_DIR", tmp_path)

        with (
            patch.object(lc, "_build_api_client", return_value=MagicMock()),
            patch.object(k8s_client, "CoreV1Api", return_value=mock_core),
            patch.object(k8s_client, "RbacAuthorizationV1Api", return_value=mock_rbac),
        ):
            sid = str(uuid.uuid4())
            lc.reclaim_learner_credentials(sid, "lab-ns", "/fake/kc")  # must not raise

    def test_k8s_error_logged_not_raised(self, tmp_path, monkeypatch):
        from backend.labgen import learner_credentials as lc

        monkeypatch.setattr(
            lc, "_build_api_client",
            lambda path: (_ for _ in ()).throw(Exception("k8s unreachable")),
        )
        monkeypatch.setattr(lc, "_CRED_BASE_DIR", tmp_path)

        sid = str(uuid.uuid4())
        lc.reclaim_learner_credentials(sid, "lab-ns", "/fake/kc")  # must not raise

    def test_removes_local_directory(self, tmp_path, monkeypatch):
        from backend.labgen import learner_credentials as lc

        monkeypatch.setattr(
            lc, "_build_api_client",
            lambda path: (_ for _ in ()).throw(Exception("no k8s")),
        )
        monkeypatch.setattr(lc, "_CRED_BASE_DIR", tmp_path)

        sid = str(uuid.uuid4())
        cred_dir = tmp_path / sid
        cred_dir.mkdir()
        (cred_dir / "config").write_text("fake")

        lc.reclaim_learner_credentials(sid, "lab-ns", "/fake/kc")

        assert not (cred_dir / "config").exists()
        assert not cred_dir.exists()

    def test_missing_local_files_tolerated(self, tmp_path, monkeypatch):
        from backend.labgen import learner_credentials as lc

        monkeypatch.setattr(
            lc, "_build_api_client",
            lambda path: (_ for _ in ()).throw(Exception("no k8s")),
        )
        monkeypatch.setattr(lc, "_CRED_BASE_DIR", tmp_path)

        sid = str(uuid.uuid4())
        lc.reclaim_learner_credentials(sid, "lab-ns", "/fake/kc")  # must not raise


# ═══════════════════════════════════════════════════════════════════════════════
# C. lab_kubectl_ws — WebSocket command loop
# ═══════════════════════════════════════════════════════════════════════════════

def _make_lab_session(
    session_id: str = None,
    username: str = "learner-1",
    status: LabSessionStatus = LabSessionStatus.LAB_ACTIVE,
) -> LabSessionState:
    sid = session_id or str(uuid.uuid4())
    return LabSessionState(
        session_id=sid,
        lab_id="test-lab",
        student_username=username,
        vm_id="401",
        lab_session_status=status,
        namespace=f"lab-{sid}",
    )


def _mock_config(kubeconfig_path: str = "/fake/kc") -> MagicMock:
    cfg = MagicMock()
    cfg.LABGEN_K8S_PLATFORM_KUBECONFIG_PATH = kubeconfig_path
    return cfg


class TestLabKubectlWsCommandLoop:
    """WebSocket tests covering auth layers 4-5 and command processing."""

    @pytest.fixture
    def client(self):
        from backend.main import app
        from fastapi.testclient import TestClient
        return TestClient(app)

    @pytest.fixture
    def user_token(self):
        from backend.auth import auth_manager
        return auth_manager.create_session("ws-cov-user")

    def test_rejects_ownership_mismatch(self, client, user_token):
        import backend.labgen.lab_kubectl_ws as ws_mod
        session_id = str(uuid.uuid4())
        mock_repo = MagicMock()
        mock_repo.get.return_value = _make_lab_session(session_id, username="other-user")

        with patch("backend.main.get_session_repository", return_value=mock_repo):
            with client.websocket_connect(
                f"/ws/lab-kubectl/{session_id}",
                cookies={"session_token": user_token},
            ) as ws:
                msg = ws.receive_json()
        assert msg["type"] == "closed"
        assert msg["reason"] == "auth_error"

    def test_rejects_session_not_active(self, client, user_token):
        session_id = str(uuid.uuid4())
        mock_repo = MagicMock()
        mock_repo.get.return_value = _make_lab_session(
            session_id, username="ws-cov-user", status=LabSessionStatus.LAB_CLOSED
        )

        with patch("backend.main.get_session_repository", return_value=mock_repo):
            with client.websocket_connect(
                f"/ws/lab-kubectl/{session_id}",
                cookies={"session_token": user_token},
            ) as ws:
                msg = ws.receive_json()
        assert msg["type"] == "closed"
        assert msg["reason"] == "session_not_active"

    def test_rejects_completed_session(self, client, user_token):
        session_id = str(uuid.uuid4())
        mock_repo = MagicMock()
        mock_repo.get.return_value = _make_lab_session(
            session_id, username="ws-cov-user", status=LabSessionStatus.LAB_COMPLETED
        )

        with patch("backend.main.get_session_repository", return_value=mock_repo):
            with client.websocket_connect(
                f"/ws/lab-kubectl/{session_id}",
                cookies={"session_token": user_token},
            ) as ws:
                msg = ws.receive_json()
        assert msg["type"] == "closed"
        assert msg["reason"] == "session_not_active"

    def test_no_platform_kubeconfig_sends_error(self, client, user_token):
        import backend.labgen.lab_kubectl_ws as ws_mod
        session_id = str(uuid.uuid4())
        mock_repo = MagicMock()
        mock_repo.get.return_value = _make_lab_session(session_id, username="ws-cov-user")

        with (
            patch("backend.main.get_session_repository", return_value=mock_repo),
            patch.object(ws_mod, "config", _mock_config("")),
        ):
            with client.websocket_connect(
                f"/ws/lab-kubectl/{session_id}",
                cookies={"session_token": user_token},
            ) as ws:
                msg = ws.receive_json()
        assert msg["type"] in ("error", "closed")

    def test_sends_ready_on_active_session(self, client, user_token):
        import backend.labgen.lab_kubectl_ws as ws_mod
        session_id = str(uuid.uuid4())
        mock_repo = MagicMock()
        mock_repo.get.return_value = _make_lab_session(session_id, username="ws-cov-user")

        with (
            patch("backend.main.get_session_repository", return_value=mock_repo),
            patch.object(ws_mod, "config", _mock_config()),
            patch(
                "backend.labgen.lab_kubectl_ws.learner_credentials.ensure_learner_credentials",
                return_value=f"/tmp/fake-{session_id}/config",
            ),
            patch(
                "backend.labgen.lab_kubectl_ws.learner_credentials.reclaim_learner_credentials"
            ),
        ):
            with client.websocket_connect(
                f"/ws/lab-kubectl/{session_id}",
                cookies={"session_token": user_token},
            ) as ws:
                msg = ws.receive_json()

        assert msg["type"] == "ready"
        assert "namespace" in msg
        assert f"lab-{session_id}" in msg["namespace"]

    def test_credential_creation_failure_sends_error(self, client, user_token):
        import backend.labgen.lab_kubectl_ws as ws_mod
        session_id = str(uuid.uuid4())
        mock_repo = MagicMock()
        mock_repo.get.return_value = _make_lab_session(session_id, username="ws-cov-user")

        with (
            patch("backend.main.get_session_repository", return_value=mock_repo),
            patch.object(ws_mod, "config", _mock_config()),
            patch(
                "backend.labgen.lab_kubectl_ws.learner_credentials.ensure_learner_credentials",
                side_effect=Exception("K8s unavailable"),
            ),
            patch(
                "backend.labgen.lab_kubectl_ws.learner_credentials.reclaim_learner_credentials"
            ),
        ):
            with client.websocket_connect(
                f"/ws/lab-kubectl/{session_id}",
                cookies={"session_token": user_token},
            ) as ws:
                msg = ws.receive_json()
        assert msg["type"] in ("error", "closed")

    def test_blocked_command_returns_blocked_message(self, client, user_token):
        import backend.labgen.lab_kubectl_ws as ws_mod
        session_id = str(uuid.uuid4())
        mock_repo = MagicMock()
        mock_repo.get.return_value = _make_lab_session(session_id, username="ws-cov-user")

        with (
            patch("backend.main.get_session_repository", return_value=mock_repo),
            patch.object(ws_mod, "config", _mock_config()),
            patch(
                "backend.labgen.lab_kubectl_ws.learner_credentials.ensure_learner_credentials",
                return_value=f"/tmp/fake-{session_id}/config",
            ),
            patch(
                "backend.labgen.lab_kubectl_ws.learner_credentials.reclaim_learner_credentials"
            ),
        ):
            with client.websocket_connect(
                f"/ws/lab-kubectl/{session_id}",
                cookies={"session_token": user_token},
            ) as ws:
                ws.receive_json()  # ready
                ws.send_json({"type": "command", "cmd": "kubectl get namespaces"})
                msg = ws.receive_json()

        assert msg["type"] == "blocked"
        assert msg.get("text")

    def test_blocked_secret_yaml_output(self, client, user_token):
        import backend.labgen.lab_kubectl_ws as ws_mod
        session_id = str(uuid.uuid4())
        mock_repo = MagicMock()
        mock_repo.get.return_value = _make_lab_session(session_id, username="ws-cov-user")

        with (
            patch("backend.main.get_session_repository", return_value=mock_repo),
            patch.object(ws_mod, "config", _mock_config()),
            patch(
                "backend.labgen.lab_kubectl_ws.learner_credentials.ensure_learner_credentials",
                return_value=f"/tmp/fake-{session_id}/config",
            ),
            patch(
                "backend.labgen.lab_kubectl_ws.learner_credentials.reclaim_learner_credentials"
            ),
        ):
            with client.websocket_connect(
                f"/ws/lab-kubectl/{session_id}",
                cookies={"session_token": user_token},
            ) as ws:
                ws.receive_json()  # ready
                ws.send_json({"type": "command", "cmd": "kubectl get secret my-secret -o yaml"})
                msg = ws.receive_json()

        assert msg["type"] == "blocked"

    def test_blocked_config_view(self, client, user_token):
        import backend.labgen.lab_kubectl_ws as ws_mod
        session_id = str(uuid.uuid4())
        mock_repo = MagicMock()
        mock_repo.get.return_value = _make_lab_session(session_id, username="ws-cov-user")

        with (
            patch("backend.main.get_session_repository", return_value=mock_repo),
            patch.object(ws_mod, "config", _mock_config()),
            patch(
                "backend.labgen.lab_kubectl_ws.learner_credentials.ensure_learner_credentials",
                return_value=f"/tmp/fake-{session_id}/config",
            ),
            patch(
                "backend.labgen.lab_kubectl_ws.learner_credentials.reclaim_learner_credentials"
            ),
        ):
            with client.websocket_connect(
                f"/ws/lab-kubectl/{session_id}",
                cookies={"session_token": user_token},
            ) as ws:
                ws.receive_json()  # ready
                ws.send_json({"type": "command", "cmd": "kubectl config view"})
                msg = ws.receive_json()

        assert msg["type"] == "blocked"

    def test_allowed_command_returns_output(self, client, user_token):
        import backend.labgen.lab_kubectl_ws as ws_mod
        session_id = str(uuid.uuid4())
        mock_repo = MagicMock()
        mock_repo.get.return_value = _make_lab_session(session_id, username="ws-cov-user")

        mock_result = CommandResult(
            allowed=True,
            block_reason=None,
            output="NAME              DATA\nmy-app-config   2\n",
            exit_code=0,
        )

        with (
            patch("backend.main.get_session_repository", return_value=mock_repo),
            patch.object(ws_mod, "config", _mock_config()),
            patch(
                "backend.labgen.lab_kubectl_ws.learner_credentials.ensure_learner_credentials",
                return_value=f"/tmp/fake-{session_id}/config",
            ),
            patch(
                "backend.labgen.lab_kubectl_ws.learner_credentials.reclaim_learner_credentials"
            ),
            patch(
                "backend.labgen.lab_kubectl_ws.kubectl_executor.execute",
                new=AsyncMock(return_value=mock_result),
            ),
        ):
            with client.websocket_connect(
                f"/ws/lab-kubectl/{session_id}",
                cookies={"session_token": user_token},
            ) as ws:
                ws.receive_json()  # ready
                ws.send_json({"type": "command", "cmd": "kubectl get configmap my-app-config"})
                msg = ws.receive_json()

        assert msg["type"] == "output"
        assert msg["exit_code"] == 0
        assert "my-app-config" in msg["text"]

    def test_invalid_json_from_client_sends_error(self, client, user_token):
        import backend.labgen.lab_kubectl_ws as ws_mod
        session_id = str(uuid.uuid4())
        mock_repo = MagicMock()
        mock_repo.get.return_value = _make_lab_session(session_id, username="ws-cov-user")

        with (
            patch("backend.main.get_session_repository", return_value=mock_repo),
            patch.object(ws_mod, "config", _mock_config()),
            patch(
                "backend.labgen.lab_kubectl_ws.learner_credentials.ensure_learner_credentials",
                return_value=f"/tmp/fake-{session_id}/config",
            ),
            patch(
                "backend.labgen.lab_kubectl_ws.learner_credentials.reclaim_learner_credentials"
            ),
        ):
            with client.websocket_connect(
                f"/ws/lab-kubectl/{session_id}",
                cookies={"session_token": user_token},
            ) as ws:
                ws.receive_json()  # ready
                ws.send_text("not valid json {{{{")
                msg = ws.receive_json()

        assert msg["type"] == "error"

    def test_empty_command_silently_ignored(self, client, user_token):
        """Empty cmd field is silently ignored — no error response."""
        import backend.labgen.lab_kubectl_ws as ws_mod
        session_id = str(uuid.uuid4())
        mock_repo = MagicMock()
        mock_repo.get.return_value = _make_lab_session(session_id, username="ws-cov-user")

        mock_result = CommandResult(
            allowed=True, block_reason=None, output="pods listed\n", exit_code=0
        )

        with (
            patch("backend.main.get_session_repository", return_value=mock_repo),
            patch.object(ws_mod, "config", _mock_config()),
            patch(
                "backend.labgen.lab_kubectl_ws.learner_credentials.ensure_learner_credentials",
                return_value=f"/tmp/fake-{session_id}/config",
            ),
            patch(
                "backend.labgen.lab_kubectl_ws.learner_credentials.reclaim_learner_credentials"
            ),
            patch(
                "backend.labgen.lab_kubectl_ws.kubectl_executor.execute",
                new=AsyncMock(return_value=mock_result),
            ),
        ):
            with client.websocket_connect(
                f"/ws/lab-kubectl/{session_id}",
                cookies={"session_token": user_token},
            ) as ws:
                ws.receive_json()  # ready
                # Send empty cmd, then a real command to get a response
                ws.send_json({"type": "command", "cmd": ""})
                ws.send_json({"type": "command", "cmd": "kubectl get pods"})
                msg = ws.receive_json()  # should be output, not error

        assert msg["type"] == "output"

    def test_session_ends_before_command_execution(self, client, user_token):
        """When session becomes inactive before execute, command is NOT dispatched."""
        import backend.labgen.lab_kubectl_ws as ws_mod
        session_id = str(uuid.uuid4())
        active = _make_lab_session(session_id, username="ws-cov-user")
        closed = _make_lab_session(
            session_id, username="ws-cov-user", status=LabSessionStatus.LAB_CLOSED
        )

        call_count = [0]

        def get_side_effect(sid):
            call_count[0] += 1
            # First lookup (auth layers 3-5): active; second (command handler check): closed
            if call_count[0] >= 2:
                return closed
            return active

        mock_repo = MagicMock()
        mock_repo.get.side_effect = get_side_effect

        mock_execute = AsyncMock(return_value=CommandResult(
            allowed=True, block_reason=None, output="pods\n", exit_code=0
        ))

        with (
            patch("backend.main.get_session_repository", return_value=mock_repo),
            patch.object(ws_mod, "config", _mock_config()),
            patch(
                "backend.labgen.lab_kubectl_ws.learner_credentials.ensure_learner_credentials",
                return_value=f"/tmp/fake-{session_id}/config",
            ),
            patch(
                "backend.labgen.lab_kubectl_ws.learner_credentials.reclaim_learner_credentials"
            ),
            patch(
                "backend.labgen.lab_kubectl_ws.kubectl_executor.execute",
                new=mock_execute,
            ),
        ):
            with client.websocket_connect(
                f"/ws/lab-kubectl/{session_id}",
                cookies={"session_token": user_token},
            ) as ws:
                ws.receive_json()  # ready
                ws.send_json({"type": "command", "cmd": "kubectl get pods"})
                msg = ws.receive_json()

        # Session ended → error or closed; execute must NOT have been called
        assert msg["type"] in ("error", "closed")
        mock_execute.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# D. lab_session_repository — update / delete / list methods
# ═══════════════════════════════════════════════════════════════════════════════

class TestLabSessionRepository:

    @pytest.fixture
    def repo(self, tmp_path):
        from backend.labgen.lab_session_repository import LabSessionRepository
        repo_path = tmp_path / "lab_sessions.json"
        return LabSessionRepository(repo_path)

    def _new_session(self, username: str = "learner-a", vm_id: str = "401") -> LabSessionState:
        sid = str(uuid.uuid4())
        return LabSessionState(
            session_id=sid,
            lab_id="test-lab",
            student_username=username,
            vm_id=vm_id,
            lab_session_status=LabSessionStatus.LAB_ACTIVE,
            namespace=f"lab-{sid}",
        )

    def test_create_and_get(self, repo):
        s = self._new_session()
        repo.create(s)
        result = repo.get(s.session_id)
        assert result is not None
        assert result.session_id == s.session_id

    def test_update_changes_status(self, repo):
        s = self._new_session()
        repo.create(s)
        s.lab_session_status = LabSessionStatus.LAB_CLOSED
        repo.update(s)
        result = repo.get(s.session_id)
        assert result.lab_session_status == LabSessionStatus.LAB_CLOSED

    def test_delete_removes_session(self, repo):
        s = self._new_session()
        repo.create(s)
        repo.delete(s.session_id)
        assert repo.get(s.session_id) is None

    def test_delete_nonexistent_is_noop(self, repo):
        repo.delete("nonexistent-id")  # must not raise

    def test_list_by_student(self, repo):
        s1 = self._new_session("learner-a")
        s2 = self._new_session("learner-b")
        s3 = self._new_session("learner-a")
        for s in [s1, s2, s3]:
            repo.create(s)

        results = repo.list_by_student("learner-a")
        assert len(results) == 2
        assert all(r.student_username == "learner-a" for r in results)

    def test_list_all(self, repo):
        for _ in range(3):
            repo.create(self._new_session())
        results = repo.list_all()
        assert len(results) == 3

    def test_list_by_vm_id(self, repo):
        s1 = self._new_session(vm_id="401")
        s2 = self._new_session(vm_id="402")
        repo.create(s1)
        repo.create(s2)

        results = repo.list_by_vm_id("401")
        assert len(results) == 1
        assert results[0].vm_id == "401"

    def test_get_nonexistent_returns_none(self, repo):
        assert repo.get("no-such-id") is None

    def test_list_by_student_empty(self, repo):
        results = repo.list_by_student("no-such-user")
        assert results == []

    def test_list_all_empty(self, repo):
        results = repo.list_all()
        assert results == []
