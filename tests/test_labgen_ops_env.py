"""Tests for backend/labgen/ops_env.py — canonical env loader for ops scripts.

Verifies that:
- load_ops_env() loads .env then home_lab_mvp.env with correct override order
- home_lab_mvp.env values override .env values (mirrors systemd EnvironmentFile ordering)
- require_production_path=True aborts when home_lab_mvp.env is absent
- assert_production_credential_root() rejects dev/default paths
- Missing files are handled gracefully
"""
from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_env(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content))
    return p


# ---------------------------------------------------------------------------
# load_ops_env
# ---------------------------------------------------------------------------


class TestLoadOpsEnv:
    def test_loads_dot_env_values(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        dot_env = _write_env(tmp_path, ".env", "OPS_TEST_VAR=from_dot_env\n")
        monkeypatch.setenv("OPS_TEST_VAR", "")
        # Patch _HOME_LAB_ENV to a non-existent path so home_lab_env won't be loaded
        import backend.labgen.ops_env as ops_env_mod
        monkeypatch.setattr(ops_env_mod, "_HOME_LAB_ENV", tmp_path / "absent_home_lab.env")

        from backend.labgen.ops_env import load_ops_env

        result = load_ops_env(_project_root=tmp_path)
        assert result["dot_env"] == str(dot_env)
        assert result["home_lab_env"] is None

    def test_home_lab_env_overrides_dot_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """home_lab_mvp.env must win over .env for any overlapping key."""
        _write_env(
            tmp_path,
            ".env",
            "LABGEN_VERIFIER_CREDENTIAL_ROOT=creds/vm_creds\nONLY_IN_DOT=yes\n",
        )
        home_lab_env = Path("/etc/labgen/home_lab_mvp.env")

        if not home_lab_env.exists():
            pytest.skip("home_lab_mvp.env absent on this host — skipping override test")

        # Clear env so we start fresh
        monkeypatch.delenv("LABGEN_VERIFIER_CREDENTIAL_ROOT", raising=False)

        from backend.labgen.ops_env import load_ops_env

        result = load_ops_env(_project_root=tmp_path)
        assert result["home_lab_env"] == str(home_lab_env)
        # production env must have overridden the dev value
        val = os.environ.get("LABGEN_VERIFIER_CREDENTIAL_ROOT", "")
        assert "labgen-staging" in val, (
            f"Expected production path, got: {val!r}. "
            "home_lab_mvp.env override must win over .env."
        )

    def test_missing_dot_env_is_graceful(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # tmp_path has no .env
        from backend.labgen.ops_env import load_ops_env

        result = load_ops_env(_project_root=tmp_path)
        assert result["dot_env"] is None

    def test_require_production_path_exits_when_home_lab_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """require_production_path=True must sys.exit(2) when home_lab_mvp.env absent."""
        import backend.labgen.ops_env as ops_env_mod
        monkeypatch.setattr(ops_env_mod, "_HOME_LAB_ENV", tmp_path / "absent_home_lab.env")
        _write_env(tmp_path, ".env", "PROXMOX_HOST=127.0.0.1\n")

        from backend.labgen.ops_env import load_ops_env

        with pytest.raises(SystemExit) as exc_info:
            load_ops_env(_project_root=tmp_path, require_production_path=True)
        assert exc_info.value.code == 2

    def test_returns_loaded_file_paths(self, tmp_path: Path) -> None:
        dot_env = _write_env(tmp_path, ".env", "X=1\n")
        from backend.labgen.ops_env import load_ops_env

        result = load_ops_env(_project_root=tmp_path)
        assert result["dot_env"] == str(dot_env)


# ---------------------------------------------------------------------------
# assert_production_credential_root
# ---------------------------------------------------------------------------


class TestAssertProductionCredentialRoot:
    def test_accepts_production_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "LABGEN_VERIFIER_CREDENTIAL_ROOT", "/var/lib/labgen-staging/verifier-credentials"
        )
        from backend.labgen.ops_env import assert_production_credential_root

        result = assert_production_credential_root()
        assert result == "/var/lib/labgen-staging/verifier-credentials"

    def test_rejects_default_creds_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LABGEN_VERIFIER_CREDENTIAL_ROOT", "creds/vm_creds")
        from backend.labgen.ops_env import assert_production_credential_root

        with pytest.raises(SystemExit) as exc_info:
            assert_production_credential_root()
        assert exc_info.value.code == 2

    def test_rejects_empty_root(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LABGEN_VERIFIER_CREDENTIAL_ROOT", raising=False)
        from backend.labgen.ops_env import assert_production_credential_root

        with pytest.raises(SystemExit) as exc_info:
            assert_production_credential_root()
        assert exc_info.value.code == 2

    def test_rejects_unrelated_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LABGEN_VERIFIER_CREDENTIAL_ROOT", "/tmp/something")
        from backend.labgen.ops_env import assert_production_credential_root

        with pytest.raises(SystemExit) as exc_info:
            assert_production_credential_root()
        assert exc_info.value.code == 2

    def test_rejects_relative_path_with_labgen(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LABGEN_VERIFIER_CREDENTIAL_ROOT", "creds/labgen-test")
        from backend.labgen.ops_env import assert_production_credential_root

        with pytest.raises(SystemExit) as exc_info:
            assert_production_credential_root()
        assert exc_info.value.code == 2
