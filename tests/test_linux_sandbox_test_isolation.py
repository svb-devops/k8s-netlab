"""Regression: test-created Linux sandbox dirs must not pollute the shared root.

Several Linux LabGen test modules create real workspace directories under the
production-default sandbox root ``/tmp/labgen-linux-sandboxes`` (required by the
``LinuxWorkspaceManager`` allowlist) and historically left them behind. That
polluted the exact path real learner/pilot sessions use and made any host-side
residual scan impossible to pass (surfaced by the Linux Trusted Reader Pilot
Exit Review & Stabilization Gate — G-52).

``purge_test_sandboxes`` removes ONLY test-prefixed directories and must never
touch a real UUID-named session workspace.
"""
import os

import pytest

from tests._sandbox_cleanup import (
    TEST_SANDBOX_PREFIXES,
    purge_test_sandboxes,
)

pytestmark = pytest.mark.static


def test_removes_only_test_prefixed_dirs(tmp_path):
    root = str(tmp_path)
    # Test-prefixed dirs (must be removed)
    test_dirs = [
        "test-000db1c7d544",
        "test-ws-0216285bfaad",
        "learner-test-000caa88149c",
        "pytest-deadbeef",
    ]
    # Real session-style dirs (must be preserved): UUID4 names + sentinel
    real_dirs = [
        "8d9bd8db-4436-4ab5-b1f6-c1df405aff2e",
        "6cdf4dc5-7865-44cb-8667-4d400c506aba",
        "linux-sandbox",
    ]
    for name in test_dirs + real_dirs:
        os.makedirs(os.path.join(root, name))

    removed = purge_test_sandboxes(root=root, prefixes=TEST_SANDBOX_PREFIXES)

    assert removed == len(test_dirs)
    for name in test_dirs:
        assert not os.path.exists(os.path.join(root, name)), f"{name} should be purged"
    for name in real_dirs:
        assert os.path.isdir(os.path.join(root, name)), f"{name} must be preserved"


def test_does_not_follow_symlinks(tmp_path):
    """A symlink whose name matches a test prefix must not be traversed/deleted target."""
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "important.txt").write_text("keep me")

    link = root / "test-evil-link"
    os.symlink(str(outside), str(link))

    purge_test_sandboxes(root=str(root))

    # The symlink target and its contents must be untouched.
    assert (outside / "important.txt").exists()


def test_missing_root_is_noop(tmp_path):
    missing = str(tmp_path / "does-not-exist")
    assert purge_test_sandboxes(root=missing) == 0


def test_default_prefixes_cover_known_test_helpers():
    # The four observed test-helper naming patterns must all be matched.
    for name in (
        "test-abc",
        "test-ws-abc",
        "learner-test-abc",
        "pytest-abc",
    ):
        assert name.startswith(TEST_SANDBOX_PREFIXES), name
    # A real UUID session id must NOT match.
    assert not "8d9bd8db-4436-4ab5".startswith(TEST_SANDBOX_PREFIXES)
