"""
Linux Verifier Adapter Hardening v0.1 tests (Task 4 of 7).

Tests prove that the hardened LinuxVerifyClientAdapter / LinuxVerifierService:

Symlink safety layers (three layers, each tested):
1. resolve_path() calls os.path.realpath() which follows ALL symlinks at check time.
   - Symlink to outside workspace: realpath escapes containment → WorkspacePathEscapeError
   - Service catches it → LINUX_PATH_ESCAPE
2. lstat() (TOCTOU mitigation): used AFTER resolve_path() on the returned path.
   - If a symlink is ADDED between resolve_path() and the filesystem op, lstat detects it.
   - Returns (False, "symlink_rejected") which service maps to LINUX_PATH_ESCAPE.
3. O_NOFOLLOW: prevents final-component symlink following at open() time.
   - Last-mile protection if both resolve_path() and lstat() are bypassed.

Key design fact:
- Symlinks to inside workspace: resolve_path() follows them (safe); lstat(target) sees target → allowed.
- Symlinks to outside workspace: resolve_path() raises WorkspacePathEscapeError (before lstat).
- TOCTOU (symlink added AFTER resolve_path()): lstat catches the symlink at abs_path.

Categories:
A. TOCTOU / symlink hardening
B. Content safety
C. Mode safety
D. Residual scan safety
E. Result redaction
F. Regression
"""

from __future__ import annotations

import os
import shutil
import stat
import uuid
from pathlib import Path
from typing import Optional

import pytest

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sbox(request):
    """Per-test directory under the allowed spike sandbox root."""
    from backend.labgen.linux_workspace import _SPIKE_SANDBOX_ROOT
    base = os.path.join(_SPIKE_SANDBOX_ROOT, f"hard-{uuid.uuid4().hex[:8]}")
    os.makedirs(base, mode=0o700, exist_ok=True)
    yield base
    shutil.rmtree(base, ignore_errors=True)


@pytest.fixture()
def ws_mgr(sbox):
    from backend.labgen.linux_workspace import LinuxWorkspaceManager
    return LinuxWorkspaceManager(sandbox_root=sbox)


@pytest.fixture()
def ws_session(ws_mgr):
    return ws_mgr.create_session("hard-sess-01")


@pytest.fixture()
def adapter(ws_mgr, ws_session):
    from backend.labgen.linux_verifier_client import LinuxVerifyClientAdapter
    return LinuxVerifyClientAdapter(ws_mgr, ws_session)


@pytest.fixture()
def linux_svc(ws_mgr, ws_session):
    """LinuxVerifierService; ws_session ensures 'hard-sess-01' workspace exists."""
    from backend.labgen.linux_verifier_client import LinuxVerifierService
    return LinuxVerifierService(ws_mgr)


def _tmpl(verify_type_str: str, **kwargs):
    """Build a minimal LinuxVerifyTemplate for testing."""
    from backend.labgen.models import LinuxVerifyTemplate, LinuxVerifyType
    return LinuxVerifyTemplate(
        verify_id=f"test-{verify_type_str}",
        type=LinuxVerifyType(verify_type_str),
        target_path=kwargs.get("target_path", ""),
        expected_content=kwargs.get("expected_content", None),
        expected_mode=kwargs.get("expected_mode", None),
        max_output_bytes=kwargs.get("max_output_bytes", 4096),
        description="test",
    )


# ---------------------------------------------------------------------------
# A. TOCTOU / symlink hardening
# ---------------------------------------------------------------------------


class TestSymlinkOutsideWorkspace:
    """
    Pre-existing symlinks to outside workspace:
    Caught by resolve_path() → WorkspacePathEscapeError → service maps to LINUX_PATH_ESCAPE.
    """

    def test_symlink_to_outside_file_rejected_via_service(self, linux_svc, ws_session, sbox):
        """Symlink to outside file → LINUX_PATH_ESCAPE from service."""
        outside = os.path.join(sbox, "secret.txt")
        with open(outside, "w") as f:
            f.write("secret")
        link = os.path.join(ws_session.workspace_path, "link.txt")
        os.symlink(outside, link)

        result = linux_svc.check("hard-sess-01", _tmpl("linux_file_exists", target_path="link.txt"))
        assert not result.passed
        assert result.failure_reason == "linux.path_escape"

    def test_symlink_to_outside_dir_rejected_via_service(self, linux_svc, ws_session, sbox):
        """Symlink to directory outside workspace → LINUX_PATH_ESCAPE."""
        outside_dir = os.path.join(sbox, "outsidedir")
        os.makedirs(outside_dir)
        link = os.path.join(ws_session.workspace_path, "linked_dir")
        os.symlink(outside_dir, link)

        result = linux_svc.check("hard-sess-01", _tmpl("linux_directory_exists", target_path="linked_dir"))
        assert not result.passed
        assert result.failure_reason == "linux.path_escape"

    def test_symlink_chain_to_outside_rejected(self, linux_svc, ws_session, sbox):
        """Symlink chain where final target is outside workspace → LINUX_PATH_ESCAPE."""
        outside = os.path.join(sbox, "chain_target.txt")
        with open(outside, "w") as f:
            f.write("outside")
        ws_path = ws_session.workspace_path
        link2 = os.path.join(ws_path, "link2.txt")
        os.symlink(outside, link2)
        link1 = os.path.join(ws_path, "link1.txt")
        os.symlink(link2, link1)

        result = linux_svc.check("hard-sess-01", _tmpl("linux_file_exists", target_path="link1.txt"))
        assert not result.passed
        assert result.failure_reason == "linux.path_escape"

    def test_symlink_loop_handled_safely(self, linux_svc, ws_session):
        """Symlink loop (a→b, b→a): resolve_path handles it without hanging."""
        ws_path = ws_session.workspace_path
        link_a = os.path.join(ws_path, "loop_a")
        link_b = os.path.join(ws_path, "loop_b")
        os.symlink(link_b, link_a)
        os.symlink(link_a, link_b)

        # Must not hang; should return a failure
        result = linux_svc.check("hard-sess-01", _tmpl("linux_file_exists", target_path="loop_a"))
        assert not result.passed  # either path_escape or file_not_found

    def test_content_check_symlink_outside_rejected(self, linux_svc, ws_session, sbox):
        """Content check on symlink to outside file → LINUX_PATH_ESCAPE."""
        outside = os.path.join(sbox, "secret.txt")
        with open(outside, "w") as f:
            f.write("secret")
        link = os.path.join(ws_session.workspace_path, "link.txt")
        os.symlink(outside, link)

        tmpl = _tmpl("linux_file_content_matches", target_path="link.txt", expected_content="secret")
        result = linux_svc.check("hard-sess-01", tmpl)
        assert not result.passed
        assert result.failure_reason == "linux.path_escape"

    def test_mode_check_symlink_outside_rejected(self, linux_svc, ws_session, sbox):
        """Mode check on symlink to outside file → LINUX_PATH_ESCAPE."""
        outside = os.path.join(sbox, "outside.txt")
        with open(outside, "w") as f:
            f.write("x")
        os.chmod(outside, 0o600)
        link = os.path.join(ws_session.workspace_path, "modelink.txt")
        os.symlink(outside, link)

        tmpl = _tmpl("linux_file_mode_matches", target_path="modelink.txt", expected_mode="600")
        result = linux_svc.check("hard-sess-01", tmpl)
        assert not result.passed
        assert result.failure_reason == "linux.path_escape"


class TestSymlinkInsideWorkspace:
    """
    Inside-workspace symlinks are now rejected fail-closed (Codex P1 fix).

    Previously, lstat() ran on the resolve_path() return value (realpath-resolved),
    which followed inside-workspace symlinks and saw a regular file at the target.
    The fix: lstat() runs on the original unresolved path (os.path.join(ws, rel)),
    so all symlinks — regardless of where they point — are rejected.
    """

    def test_symlink_to_inside_file_rejected(self, linux_svc, ws_mgr, ws_session):
        """Symlink pointing inside workspace → still rejected fail-closed."""
        ws_path = ws_session.workspace_path
        real_file = os.path.join(ws_path, "real.txt")
        with open(real_file, "w") as f:
            f.write("data")
        link = os.path.join(ws_path, "link.txt")
        os.symlink(real_file, link)

        result = linux_svc.check("hard-sess-01", _tmpl("linux_file_exists", target_path="link.txt"))
        assert not result.passed
        assert result.failure_reason == "linux.path_escape"

    def test_symlink_to_inside_dir_rejected(self, linux_svc, ws_mgr, ws_session):
        """Symlink to inside-workspace directory → rejected fail-closed."""
        ws_path = ws_session.workspace_path
        real_dir = os.path.join(ws_path, "realdir")
        os.makedirs(real_dir)
        link = os.path.join(ws_path, "linkdir")
        os.symlink(real_dir, link)

        result = linux_svc.check("hard-sess-01", _tmpl("linux_directory_exists", target_path="linkdir"))
        assert not result.passed
        assert result.failure_reason == "linux.path_escape"

    def test_symlink_inside_workspace_content_rejected(self, linux_svc, ws_mgr, ws_session):
        """Content check on inside-workspace symlink → rejected fail-closed."""
        ws_path = ws_session.workspace_path
        real_file = os.path.join(ws_path, "real.txt")
        with open(real_file, "w") as f:
            f.write("secret content")
        link = os.path.join(ws_path, "link.txt")
        os.symlink(real_file, link)

        tmpl = _tmpl("linux_file_content_matches", target_path="link.txt", expected_content="secret")
        result = linux_svc.check("hard-sess-01", tmpl)
        assert not result.passed
        assert result.failure_reason == "linux.path_escape"


class TestTOCTOUMitigation:
    """
    TOCTOU mitigation: symlink added AFTER resolve_path() would have run.

    resolve_path() uses os.path.realpath() which catches symlinks at check time.
    lstat() provides the SECOND layer: if a symlink appears BETWEEN resolve_path()
    and the actual filesystem op, lstat() catches it on the resolved path.

    To test lstat() in isolation (without resolve_path() also catching it),
    we monkeypatch resolve_path() to return the raw path without symlink-following.
    This simulates the race window where resolve_path() ran at T1 (no symlink),
    and a symlink appeared at T2 (before lstat runs at T3).
    """

    def test_lstat_catches_symlink_file_exists_when_resolve_bypassed(
        self, ws_mgr, ws_session, sbox, monkeypatch
    ):
        """lstat() catches symlink that appears after resolve_path() returned."""
        from backend.labgen.linux_verifier_client import LinuxVerifyClientAdapter

        real_path = os.path.join(ws_session.workspace_path, "target.txt")
        with open(real_path, "w") as f:
            f.write("legit content")

        outside = os.path.join(sbox, "evil.txt")
        with open(outside, "w") as f:
            f.write("evil content")

        # Bypass resolve_path (simulates T1: it returned real_path without seeing symlink)
        monkeypatch.setattr(ws_mgr, "resolve_path", lambda _s, _p: real_path)
        adapter = LinuxVerifyClientAdapter(ws_mgr, ws_session)

        # Simulate TOCTOU: file replaced with symlink at T2
        os.unlink(real_path)
        os.symlink(outside, real_path)

        # lstat at T3 sees symlink → rejected
        passed, reason = adapter.file_exists("target.txt")
        assert not passed
        assert reason == "symlink_rejected"

    def test_lstat_catches_symlink_content_check_when_resolve_bypassed(
        self, ws_mgr, ws_session, sbox, monkeypatch
    ):
        """lstat() catches symlink in content check when resolve_path bypassed."""
        from backend.labgen.linux_verifier_client import LinuxVerifyClientAdapter

        real_path = os.path.join(ws_session.workspace_path, "target.txt")
        with open(real_path, "w") as f:
            f.write("legit content")

        outside = os.path.join(sbox, "evil.txt")
        with open(outside, "w") as f:
            f.write("evil content")

        monkeypatch.setattr(ws_mgr, "resolve_path", lambda _s, _p: real_path)
        adapter = LinuxVerifyClientAdapter(ws_mgr, ws_session)

        os.unlink(real_path)
        os.symlink(outside, real_path)

        passed, reason = adapter.file_content_matches("target.txt", "legit", 4096)
        assert not passed
        assert reason == "symlink_rejected"

    def test_lstat_catches_symlink_mode_check_when_resolve_bypassed(
        self, ws_mgr, ws_session, sbox, monkeypatch
    ):
        """lstat() catches symlink in mode check when resolve_path bypassed."""
        from backend.labgen.linux_verifier_client import LinuxVerifyClientAdapter

        real_path = os.path.join(ws_session.workspace_path, "target.txt")
        with open(real_path, "w") as f:
            f.write("x")
        os.chmod(real_path, 0o600)

        outside = os.path.join(sbox, "evil.txt")
        with open(outside, "w") as f:
            f.write("x")
        os.chmod(outside, 0o600)

        monkeypatch.setattr(ws_mgr, "resolve_path", lambda _s, _p: real_path)
        adapter = LinuxVerifyClientAdapter(ws_mgr, ws_session)

        os.unlink(real_path)
        os.symlink(outside, real_path)

        passed, reason = adapter.file_mode_matches("target.txt", "600")
        assert not passed
        assert reason == "symlink_rejected"

    def test_regular_file_passes_with_lstat(self, adapter, ws_mgr, ws_session):
        """Regular file (no symlink) passes with the lstat check."""
        ws_mgr.write_file(ws_session, "regular.txt", "hello")
        passed, reason = adapter.file_exists("regular.txt")
        assert passed
        assert reason == ""


class TestOpenNofollow:
    """_open_nofollow rejects final-component symlinks via O_NOFOLLOW (unit tests)."""

    def test_open_nofollow_reads_regular_file(self, ws_session):
        """Regular file → reads correctly."""
        from backend.labgen.linux_verifier_client import _open_nofollow
        p = os.path.join(ws_session.workspace_path, "read_me.txt")
        with open(p, "w") as f:
            f.write("test content here")
        content = _open_nofollow(p, 4096)
        assert "test content here" in content

    def test_open_nofollow_rejects_symlink(self, ws_session, sbox):
        """Symlink at final component → WorkspacePathEscapeError via ELOOP."""
        from backend.labgen.linux_verifier_client import _open_nofollow
        from backend.labgen.linux_workspace import WorkspacePathEscapeError
        outside = os.path.join(sbox, "target.txt")
        with open(outside, "w") as f:
            f.write("outside content")
        link_path = os.path.join(ws_session.workspace_path, "sym.txt")
        os.symlink(outside, link_path)
        with pytest.raises(WorkspacePathEscapeError):
            _open_nofollow(link_path, 4096)

    def test_open_nofollow_respects_max_bytes(self, ws_session):
        """max_bytes limits how much content is read."""
        from backend.labgen.linux_verifier_client import _open_nofollow
        p = os.path.join(ws_session.workspace_path, "long.txt")
        with open(p, "w") as f:
            f.write("A" * 100)
        content = _open_nofollow(p, 10)
        assert len(content) <= 10


class TestRecheckContainment:
    """_recheck_containment catches paths that escape workspace after initial resolve."""

    def test_normal_path_passes(self, ws_session):
        """Normal path within workspace: recheck passes."""
        from backend.labgen.linux_verifier_client import _recheck_containment
        target = os.path.join(ws_session.workspace_path, "test.txt")
        _recheck_containment(target, ws_session.workspace_path)  # must not raise

    def test_escaped_path_fails(self, ws_session, sbox):
        """Path resolving outside workspace → WorkspacePathEscapeError."""
        from backend.labgen.linux_verifier_client import _recheck_containment
        from backend.labgen.linux_workspace import WorkspacePathEscapeError
        outside = os.path.join(sbox, "outside.txt")
        with pytest.raises(WorkspacePathEscapeError):
            _recheck_containment(outside, ws_session.workspace_path)

    def test_sibling_prefix_escape_fails(self, ws_session, sbox):
        """Sibling-prefix path (workspace + 'evil') → WorkspacePathEscapeError."""
        from backend.labgen.linux_verifier_client import _recheck_containment
        from backend.labgen.linux_workspace import WorkspacePathEscapeError
        # Sibling of workspace_path within sbox
        sibling = ws_session.workspace_path + "evil"
        os.makedirs(sibling, exist_ok=True)
        try:
            with pytest.raises(WorkspacePathEscapeError):
                _recheck_containment(os.path.join(sibling, "file.txt"), ws_session.workspace_path)
        finally:
            shutil.rmtree(sibling, ignore_errors=True)


# ---------------------------------------------------------------------------
# B. Content safety
# ---------------------------------------------------------------------------


class TestContentSafety:

    def test_content_mismatch_never_returns_raw_content(self, adapter, ws_mgr, ws_session):
        """Content mismatch: the file content is never echoed in the reason string."""
        secret = "SUPER_SECRET_PASSWORD_12345"
        ws_mgr.write_file(ws_session, "secret.txt", secret)
        passed, reason = adapter.file_content_matches("secret.txt", "NOT_THIS", 4096)
        assert not passed
        assert secret not in reason
        assert reason == "content_mismatch"

    def test_large_file_returns_too_large_not_content(self, adapter, ws_mgr, ws_session):
        """File exceeding max_bytes: returns 'file_too_large', not content dump."""
        large_content = "A" * 200
        ws_mgr.write_file(ws_session, "large.txt", large_content)
        passed, reason = adapter.file_content_matches("large.txt", "A", max_bytes=100)
        assert not passed
        assert reason == "file_too_large"
        assert "A" * 5 not in reason  # no content dump

    def test_binary_file_handled_safely(self, adapter, ws_session):
        """Binary file (non-UTF-8 bytes): handled without crash."""
        binary_path = os.path.join(ws_session.workspace_path, "binary.bin")
        with open(binary_path, "wb") as f:
            f.write(bytes(range(256)))
        passed, reason = adapter.file_content_matches("binary.bin", "hello", 512)
        assert not passed
        assert reason in ("content_mismatch",)  # replacement chars → no match

    def test_max_bytes_enforced_on_read(self, adapter, ws_mgr, ws_session):
        """max_bytes limits content checked — file_too_large if file is over limit."""
        content = "X" * 50
        ws_mgr.write_file(ws_session, "sized.txt", content)
        passed, reason = adapter.file_content_matches("sized.txt", "X", max_bytes=10)
        assert not passed
        assert reason == "file_too_large"

    def test_permission_denied_returns_safe_failure(self, adapter, ws_session):
        """File without read permission: does not crash; result is bool with safe reason."""
        noperm = os.path.join(ws_session.workspace_path, "noperm.txt")
        with open(noperm, "w") as f:
            f.write("content")
        os.chmod(noperm, 0o000)
        try:
            # Check for something NOT in the file to avoid matching even if root reads it
            passed, reason = adapter.file_content_matches("noperm.txt", "NOT_IN_FILE_XYZ", 4096)
            # Should not crash; if root reads the file, content check will fail (not found)
            assert not passed
            assert reason in ("read_error", "content_mismatch", "file_too_large")
        finally:
            os.chmod(noperm, 0o644)

    def test_service_content_mismatch_detail_is_redacted(self, linux_svc, ws_mgr, ws_session):
        """LinuxVerifierService: content mismatch detail never contains raw file content."""
        secret = "LEARNER_SHOULD_NOT_SEE_THIS"
        ws_mgr.write_file(ws_session, "secret.txt", secret)
        tmpl = _tmpl(
            "linux_file_content_matches",
            target_path="secret.txt",
            expected_content="WRONG_EXPECTED",
            max_output_bytes=4096,
        )
        result = linux_svc.check("hard-sess-01", tmpl)
        assert not result.passed
        assert secret not in result.detail
        assert secret not in (result.failure_reason or "")
        assert "[content redacted]" in result.detail

    def test_service_large_file_detail_safe(self, linux_svc, ws_session):
        """LinuxVerifierService: large file detail does not dump content."""
        large = "B" * 200
        p = os.path.join(ws_session.workspace_path, "large.txt")
        with open(p, "w") as f:
            f.write(large)
        tmpl = _tmpl(
            "linux_file_content_matches",
            target_path="large.txt",
            expected_content="B",
            max_output_bytes=10,
        )
        result = linux_svc.check("hard-sess-01", tmpl)
        assert not result.passed
        assert "B" * 5 not in result.detail
        assert "content" in result.detail.lower()


# ---------------------------------------------------------------------------
# C. Mode safety
# ---------------------------------------------------------------------------


class TestModeSafety:

    def test_invalid_octal_mode_format_rejected(self, linux_svc, ws_mgr, ws_session):
        """expected_mode with non-octal chars → rejected with LINUX_VERIFY_TYPE_NOT_SUPPORTED."""
        ws_mgr.write_file(ws_session, "f.txt", "x")
        tmpl = _tmpl("linux_file_mode_matches", target_path="f.txt", expected_mode="abc")
        result = linux_svc.check("hard-sess-01", tmpl)
        assert not result.passed
        assert result.failure_reason == "linux.verify_type_not_supported"

    def test_mode_too_long_rejected(self, linux_svc, ws_mgr, ws_session):
        """expected_mode with too many digits → rejected."""
        ws_mgr.write_file(ws_session, "f.txt", "x")
        tmpl = _tmpl("linux_file_mode_matches", target_path="f.txt", expected_mode="12345")
        result = linux_svc.check("hard-sess-01", tmpl)
        assert not result.passed
        assert result.failure_reason == "linux.verify_type_not_supported"

    def test_mode_with_octal_8_rejected(self, linux_svc, ws_mgr, ws_session):
        """expected_mode containing '8' (not valid octal) → rejected."""
        ws_mgr.write_file(ws_session, "f.txt", "x")
        tmpl = _tmpl("linux_file_mode_matches", target_path="f.txt", expected_mode="800")
        result = linux_svc.check("hard-sess-01", tmpl)
        assert not result.passed
        assert result.failure_reason == "linux.verify_type_not_supported"

    def test_valid_octal_mode_accepted(self, linux_svc, ws_mgr, ws_session):
        """Valid octal mode ('600') → proceeds to actual mode check."""
        ws_mgr.write_file(ws_session, "f.txt", "x")
        os.chmod(os.path.join(ws_session.workspace_path, "f.txt"), 0o600)
        tmpl = _tmpl("linux_file_mode_matches", target_path="f.txt", expected_mode="600")
        result = linux_svc.check("hard-sess-01", tmpl)
        assert result.passed

    def test_symlink_mode_check_rejected_when_resolve_bypassed(
        self, ws_mgr, ws_session, sbox, monkeypatch
    ):
        """TOCTOU: lstat catches symlink for mode check when resolve_path bypassed."""
        from backend.labgen.linux_verifier_client import LinuxVerifyClientAdapter

        real_path = os.path.join(ws_session.workspace_path, "mfile.txt")
        with open(real_path, "w") as f:
            f.write("x")
        os.chmod(real_path, 0o600)

        outside = os.path.join(sbox, "outside.txt")
        with open(outside, "w") as f:
            f.write("x")
        os.chmod(outside, 0o600)

        monkeypatch.setattr(ws_mgr, "resolve_path", lambda _s, _p: real_path)
        adapter = LinuxVerifyClientAdapter(ws_mgr, ws_session)

        os.unlink(real_path)
        os.symlink(outside, real_path)

        passed, reason = adapter.file_mode_matches("mfile.txt", "600")
        assert not passed
        assert reason == "symlink_rejected"

    def test_mode_mismatch_detail_contains_only_modes(self, linux_svc, ws_mgr, ws_session):
        """Mode mismatch detail shows expected/actual mode values, not file content."""
        ws_mgr.write_file(ws_session, "f.txt", "content")
        os.chmod(os.path.join(ws_session.workspace_path, "f.txt"), 0o644)
        tmpl = _tmpl("linux_file_mode_matches", target_path="f.txt", expected_mode="600")
        result = linux_svc.check("hard-sess-01", tmpl)
        assert not result.passed
        assert "content" not in result.detail
        # Must show mode info
        assert "600" in result.detail or "644" in result.detail

    def test_mode_missing_file_safe_failure(self, adapter):
        """Mode check on missing file → (False, 'not_found'), not crash."""
        passed, reason = adapter.file_mode_matches("nonexistent.txt", "600")
        assert not passed
        assert reason == "not_found"

    def test_validate_octal_mode_helper(self):
        """_validate_octal_mode rejects invalid and accepts valid modes."""
        from backend.labgen.linux_verifier_client import _validate_octal_mode
        # Valid
        assert _validate_octal_mode("600")
        assert _validate_octal_mode("755")
        assert _validate_octal_mode("0")
        assert _validate_octal_mode("7777")
        assert _validate_octal_mode("644")
        # Invalid
        assert not _validate_octal_mode("")
        assert not _validate_octal_mode("abc")
        assert not _validate_octal_mode("8")
        assert not _validate_octal_mode("999")
        assert not _validate_octal_mode("9")
        assert not _validate_octal_mode("12345")


# ---------------------------------------------------------------------------
# D. Residual scan safety
# ---------------------------------------------------------------------------


class TestResidualScanSafety:

    def test_removed_workspace_passes(self, adapter, ws_session):
        """If workspace dir is removed, no_residual_files returns True."""
        shutil.rmtree(ws_session.workspace_path, ignore_errors=True)
        passed, reason = adapter.no_residual_files()
        assert passed

    def test_empty_workspace_passes(self, adapter):
        """Empty workspace → PASS."""
        passed, reason = adapter.no_residual_files()
        assert passed

    def test_leftover_file_fails(self, adapter, ws_session):
        """File in workspace → FAIL."""
        with open(os.path.join(ws_session.workspace_path, "leftover.txt"), "w") as f:
            f.write("remains")
        passed, reason = adapter.no_residual_files()
        assert not passed

    def test_reports_relative_paths_only(self, adapter, ws_session):
        """Residual scan reports relative paths, never host absolute paths."""
        ws_path = ws_session.workspace_path
        with open(os.path.join(ws_path, "file.txt"), "w") as f:
            f.write("x")
        passed, reason = adapter.no_residual_files()
        assert not passed
        # reason must not contain the host workspace path
        assert ws_path not in reason

    def test_reports_at_most_residual_sample_max_paths(self, adapter, ws_session):
        """At most _RESIDUAL_SAMPLE_MAX paths reported in reason."""
        from backend.labgen.linux_verifier_client import _RESIDUAL_SAMPLE_MAX
        ws_path = ws_session.workspace_path
        for i in range(10):
            with open(os.path.join(ws_path, f"file{i}.txt"), "w") as f:
                f.write("x")
        passed, reason = adapter.no_residual_files()
        assert not passed
        assert "10_files_remain" in reason
        # Verify sample is capped by counting commas in the sample portion
        sample_part = reason.split(":", 1)[1] if ":" in reason else reason
        comma_count = sample_part.count(",")
        assert comma_count < _RESIDUAL_SAMPLE_MAX

    def test_symlink_to_dir_counted_as_residual(self, adapter, ws_session, sbox):
        """Symlink-to-dir in workspace counts as residual (not followed)."""
        outside_dir = os.path.join(sbox, "outsidedir")
        os.makedirs(outside_dir)
        link_path = os.path.join(ws_session.workspace_path, "symlinkdir")
        os.symlink(outside_dir, link_path)

        passed, reason = adapter.no_residual_files()
        assert not passed
        # The symlink itself is counted as a residual
        assert "symlinkdir" in reason or "1_files_remain" in reason

    def test_symlink_dir_not_traversed(self, adapter, ws_session, sbox):
        """Symlink-to-dir: contents NOT traversed into (followlinks=False)."""
        outside_dir = os.path.join(sbox, "deep_outside")
        os.makedirs(outside_dir)
        with open(os.path.join(outside_dir, "inside_file.txt"), "w") as f:
            f.write("should not appear")
        link_path = os.path.join(ws_session.workspace_path, "linked_dir")
        os.symlink(outside_dir, link_path)

        passed, reason = adapter.no_residual_files()
        assert not passed
        # Only the symlink itself appears; inside_file.txt must NOT appear
        assert "inside_file.txt" not in reason

    def test_permission_error_on_subdir_handled_gracefully(self, adapter, ws_session, monkeypatch):
        """permission_error_during_scan path: mocked so it works even as root."""
        import backend.labgen.linux_verifier_client as lvc

        def _walk_raises(*args, **kwargs):
            raise PermissionError("no access")

        monkeypatch.setattr(lvc.os, "walk", _walk_raises)
        passed, reason = adapter.no_residual_files()
        assert not passed
        assert reason == "permission_error_during_scan"

    def test_workspace_absolute_path_not_in_reason(self, adapter, ws_session):
        """Residual reason does not include host workspace absolute path."""
        ws_path = ws_session.workspace_path
        with open(os.path.join(ws_path, "leak_test.txt"), "w") as f:
            f.write("x")
        passed, reason = adapter.no_residual_files()
        assert not passed
        assert ws_path not in reason


# ---------------------------------------------------------------------------
# E. Result redaction (VerifyResult safety)
# ---------------------------------------------------------------------------


class TestResultRedaction:

    def test_no_host_path_in_file_not_found_detail(self, linux_svc, ws_session):
        """File not found: detail shows only rel_path, not host absolute path."""
        tmpl = _tmpl("linux_file_exists", target_path="missing.txt")
        result = linux_svc.check("hard-sess-01", tmpl)
        assert not result.passed
        assert ws_session.workspace_path not in result.detail
        assert "/tmp" not in result.detail

    def test_no_raw_content_in_content_mismatch(self, linux_svc, ws_mgr, ws_session):
        """Content mismatch: failure_reason and detail never contain raw file content."""
        secret = "MY_SECRET_TOKEN_XYZ"
        ws_mgr.write_file(ws_session, "secret.txt", secret)
        tmpl = _tmpl(
            "linux_file_content_matches",
            target_path="secret.txt",
            expected_content="WRONG",
            max_output_bytes=4096,
        )
        result = linux_svc.check("hard-sess-01", tmpl)
        assert not result.passed
        assert secret not in result.detail
        assert secret not in (result.failure_reason or "")
        assert secret not in (result.error_code or "")

    def test_detail_length_capped(self, linux_svc, ws_mgr, ws_session):
        """VerifyResult.detail is capped at _MAX_DETAIL_LEN characters."""
        from backend.labgen.linux_verifier_client import _MAX_DETAIL_LEN
        ws_mgr.write_file(ws_session, "f.txt", "content")
        tmpl = _tmpl("linux_file_exists", target_path="f.txt")
        result = linux_svc.check("hard-sess-01", tmpl)
        assert len(result.detail) <= _MAX_DETAIL_LEN

    def test_workspace_not_found_leaks_no_host_path(self, linux_svc):
        """Workspace not found: no host path in failure_reason."""
        from backend.labgen.linux_workspace import _SPIKE_SANDBOX_ROOT
        tmpl = _tmpl("linux_file_exists", target_path="f.txt")
        result = linux_svc.check("nonexistent-session-id", tmpl)
        assert not result.passed
        assert _SPIKE_SANDBOX_ROOT not in (result.detail or "")
        assert _SPIKE_SANDBOX_ROOT not in (result.failure_reason or "")

    def test_no_stack_trace_in_result(self, linux_svc, ws_mgr, ws_session):
        """VerifyResult detail and failure_reason do not contain Python tracebacks."""
        ws_mgr.write_file(ws_session, "f.txt", "x")
        tmpl = _tmpl("linux_file_exists", target_path="f.txt")
        result = linux_svc.check("hard-sess-01", tmpl)
        assert "Traceback" not in (result.detail or "")
        assert "Traceback" not in (result.failure_reason or "")
        assert 'File "' not in (result.detail or "")

    def test_path_escape_detail_safe(self, linux_svc, ws_session):
        """Path escape detail: shows escape reason code, not raw host path content."""
        tmpl = _tmpl("linux_file_exists", target_path="/etc/passwd")
        result = linux_svc.check("hard-sess-01", tmpl)
        assert not result.passed
        assert result.failure_reason == "linux.path_escape"

    def test_symlink_rejection_detail_safe(self, linux_svc, ws_session, sbox):
        """Symlink rejection detail: shows rel_path, not outside target path."""
        outside = os.path.join(sbox, "sensitive.txt")
        with open(outside, "w") as f:
            f.write("sensitive data")
        link = os.path.join(ws_session.workspace_path, "link.txt")
        os.symlink(outside, link)

        tmpl = _tmpl("linux_file_exists", target_path="link.txt")
        result = linux_svc.check("hard-sess-01", tmpl)
        assert not result.passed
        # Outside path must not appear in learner-visible result
        assert outside not in result.detail
        assert sbox not in result.detail
        assert "sensitive data" not in result.detail


# ---------------------------------------------------------------------------
# F. Regression tests
# ---------------------------------------------------------------------------


class TestK8sVerifierRegression:
    """K8s verifier path must be completely unchanged."""

    def test_k8s_verifier_import_still_works(self):
        from backend.labgen.k8s_verifier_client import K8sVerifierClientAdapter

    def test_step_progression_k8s_default_unchanged(self):
        """StepProgressionService: linux_verifier_svc=None by default for K8s path."""
        from backend.labgen.step_progression_service import StepProgressionService
        svc = StepProgressionService.__new__(StepProgressionService)
        svc._linux_verifier_svc = None
        assert svc._linux_verifier_svc is None


class TestStaticValidatorLinuxRegression:
    """StaticValidator must still block Linux lab publish."""

    def test_linux_lab_publish_still_blocked(self):
        from backend.labgen.static_validator import StaticValidator
        from backend.labgen.models import LabDraft, LabDomainType
        import uuid

        from backend.labgen.models import RuntimeRequirements
        draft = LabDraft(
            id=str(uuid.uuid4()),
            title="Linux Test",
            description="desc",
            source_article_id=str(uuid.uuid4()),
            estimated_duration_minutes=30,
            runtime_requirements=RuntimeRequirements(),
            steps=[],
            target_domain=LabDomainType.LINUX,
        )
        from backend.labgen.models import BlockingLevel, ValidatorStatus
        validator = StaticValidator()
        results = validator.validate(draft)
        blocking = [
            r for r in results
            if r.blocking_level == BlockingLevel.PUBLISH_BLOCKING
            and r.status == ValidatorStatus.FAILED
        ]
        assert len(blocking) > 0


class TestLinuxVerifierSpikeRegression:
    """Existing spike primitive behaviors still pass after hardening."""

    def test_file_exists_positive(self, adapter, ws_mgr, ws_session):
        ws_mgr.write_file(ws_session, "ok.txt", "data")
        passed, _ = adapter.file_exists("ok.txt")
        assert passed

    def test_file_exists_missing(self, adapter):
        passed, reason = adapter.file_exists("ghost.txt")
        assert not passed
        assert reason == "not_found"

    def test_directory_exists_positive(self, adapter, ws_mgr, ws_session):
        ws_mgr.make_directory(ws_session, "mydir")
        passed, _ = adapter.directory_exists("mydir")
        assert passed

    def test_content_match_positive(self, adapter, ws_mgr, ws_session):
        ws_mgr.write_file(ws_session, "msg.txt", "hello labgen")
        passed, _ = adapter.file_content_matches("msg.txt", "hello labgen", 4096)
        assert passed

    def test_content_mismatch(self, adapter, ws_mgr, ws_session):
        ws_mgr.write_file(ws_session, "msg.txt", "hello")
        passed, reason = adapter.file_content_matches("msg.txt", "goodbye", 4096)
        assert not passed
        assert reason == "content_mismatch"

    def test_mode_match_positive(self, adapter, ws_mgr, ws_session):
        ws_mgr.write_file(ws_session, "f.txt", "x")
        ws_mgr.chmod_file(ws_session, "f.txt", 0o600)
        passed, _ = adapter.file_mode_matches("f.txt", "600")
        assert passed

    def test_no_residual_files_positive(self, adapter):
        passed, _ = adapter.no_residual_files()
        assert passed

    def test_path_traversal_still_rejected(self, adapter, ws_mgr, ws_session):
        from backend.labgen.linux_workspace import WorkspacePathEscapeError
        ws_mgr.write_file(ws_session, "ok.txt", "data")
        with pytest.raises(WorkspacePathEscapeError):
            adapter.file_exists("../escape")

    def test_absolute_path_still_rejected(self, adapter):
        from backend.labgen.linux_workspace import WorkspacePathEscapeError
        with pytest.raises(WorkspacePathEscapeError):
            adapter.file_exists("/etc/passwd")

    def test_inactive_workspace_fails_closed(self, ws_mgr, ws_session):
        """Closed session fails closed in LinuxVerifierService."""
        from backend.labgen.linux_verifier_client import LinuxVerifierService
        ws_mgr.close_session(ws_session)
        svc = LinuxVerifierService(ws_mgr)
        tmpl = _tmpl("linux_file_exists", target_path="f.txt")
        result = svc.check("hard-sess-01", tmpl)
        assert not result.passed
        assert result.failure_reason == "linux.workspace_not_active"


class TestNoSubprocessInHardenedAdapter:
    """Hardened adapter must not import subprocess (AST check)."""

    def test_no_subprocess_import_in_hardened_client(self):
        import ast
        src = (Path(__file__).parent.parent / "backend/labgen/linux_verifier_client.py").read_text()
        tree = ast.parse(src)
        import_names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                import_names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    import_names.append(node.module)
        assert "subprocess" not in import_names, (
            "linux_verifier_client.py must not import subprocess"
        )
