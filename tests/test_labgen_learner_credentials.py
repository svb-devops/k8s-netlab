"""
learner_credentials — unit tests.

Coverage areas:
  A. _validate_session_id: valid / invalid session IDs
  B. _substitute_namespace in snapshot
  C. Credential path derivation
  D. reclaim_learner_credentials: tolerates missing files (idempotent)
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.labgen.learner_credentials import (
    _validate_session_id,
    get_kubeconfig_path,
    _CRED_BASE_DIR,
)

pytestmark = pytest.mark.static


# ── A. Session ID validation ──────────────────────────────────────────────────

class TestValidateSessionId:

    def test_valid_uuid(self):
        sid = str(uuid.uuid4())
        _validate_session_id(sid)  # should not raise

    @pytest.mark.parametrize("bad_sid", [
        "not-a-uuid",
        "",
        "../../../../etc/passwd",
        "12345678-1234-1234-1234-12345678GHIJ",  # non-hex chars
        "12345678-1234-1234-1234-1234567890ab-extra",  # too long
    ])
    def test_invalid_session_id_raises(self, bad_sid):
        with pytest.raises(ValueError, match="UUID"):
            _validate_session_id(bad_sid)


# ── B. get_kubeconfig_path ────────────────────────────────────────────────────

class TestGetKubeconfigPath:

    def test_returns_none_when_not_exists(self):
        sid = str(uuid.uuid4())
        result = get_kubeconfig_path(sid)
        assert result is None

    def test_returns_path_when_exists(self, tmp_path, monkeypatch):
        sid = str(uuid.uuid4())
        cred_dir = tmp_path / sid
        cred_dir.mkdir()
        (cred_dir / "config").write_text("kubeconfig content")

        monkeypatch.setattr(
            "backend.labgen.learner_credentials._CRED_BASE_DIR", tmp_path
        )
        result = get_kubeconfig_path(sid)
        assert result is not None
        assert result.name == "config"


# ── C. reclaim_learner_credentials: tolerates missing K8s and files ───────────

class TestReclaimLearnerCredentials:

    def test_reclaim_tolerates_missing_k8s(self, tmp_path, monkeypatch):
        """Reclaim should not raise even when K8s API calls fail."""
        from backend.labgen import learner_credentials as lc

        sid = str(uuid.uuid4())
        ns = f"lab-{sid}"

        # Patch _build_api_client to raise so we test tolerance
        monkeypatch.setattr(lc, "_build_api_client", lambda path: (_ for _ in ()).throw(Exception("no k8s")))
        monkeypatch.setattr(lc, "_CRED_BASE_DIR", tmp_path)

        # Should not raise
        lc.reclaim_learner_credentials(sid, ns, "/fake/kubeconfig")

    def test_reclaim_removes_local_files(self, tmp_path, monkeypatch):
        """Reclaim removes the session kubeconfig file and directory."""
        from backend.labgen import learner_credentials as lc

        sid = str(uuid.uuid4())
        ns = f"lab-{sid}"

        # Create fake kubeconfig
        cred_dir = tmp_path / sid
        cred_dir.mkdir()
        config_file = cred_dir / "config"
        config_file.write_text("fake kubeconfig")

        monkeypatch.setattr(lc, "_build_api_client", lambda path: (_ for _ in ()).throw(Exception("no k8s")))
        monkeypatch.setattr(lc, "_CRED_BASE_DIR", tmp_path)

        lc.reclaim_learner_credentials(sid, ns, "/fake/kubeconfig")

        assert not config_file.exists()
        assert not cred_dir.exists()


# ── D. _write_kubeconfig: path traversal guard ───────────────────────────────

class TestPathSecurity:

    def test_session_id_path_traversal_rejected(self):
        """Traversal session IDs are rejected before any filesystem access."""
        bad_sids = [
            "../../etc/passwd",
            "../../../root/.kube/config",
            "abc/../../../etc/shadow",
        ]
        for bad_sid in bad_sids:
            with pytest.raises(ValueError, match="UUID"):
                _validate_session_id(bad_sid)
