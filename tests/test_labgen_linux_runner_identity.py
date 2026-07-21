"""
Regression tests for backend.labgen.linux_runner_identity.

Bug this closes: the Linux command executor previously ran learner commands
under the same UID as the (root) API process, which let root bypass the exact
directory execute/traverse DAC check the "chmod despite correct mode"
Golden Topic lab depends on (see
docs/labgen/linux/LINUX_GOLDEN_TOPIC_1_RUNTIME_BLOCKED_v0.1.md for the live
reproduction). Fix: resolve_runner_identity() validates a real, non-root
system account exists before any Linux command executes, and fails closed
(raises, never falls back to root) if the account is missing or misconfigured.
"""

import grp
import os
import pwd

import pytest

from backend.labgen.linux_runner_identity import (
    RunnerIdentityError,
    resolve_runner_identity,
)

pytestmark = pytest.mark.static


class TestResolveRunnerIdentityHappyPath:
    """These assume scripts/install-labgen-linux-runner.sh has been run on
    this host, matching production/deployment. If the account is absent,
    that itself is the bug this module exists to catch — so we assert
    directly rather than skip."""

    def test_resolves_real_installed_runner_account(self):
        identity = resolve_runner_identity("labgen-linux-runner", "labgen-linux-runner")
        assert identity.username == "labgen-linux-runner"
        assert identity.uid != 0
        assert identity.gid != 0

    def test_resolved_identity_matches_system_records(self):
        identity = resolve_runner_identity("labgen-linux-runner", "labgen-linux-runner")
        pw = pwd.getpwnam("labgen-linux-runner")
        gr = grp.getgrnam("labgen-linux-runner")
        assert identity.uid == pw.pw_uid
        assert identity.gid == gr.gr_gid

    def test_installed_runner_has_no_supplementary_groups(self):
        # Documents the actual installed state as a regression guard — if a
        # future deploy step accidentally adds this account to a group
        # (e.g. sudo, docker), this test catches it directly, independent of
        # resolve_runner_identity's own enforcement.
        gid = grp.getgrnam("labgen-linux-runner").gr_gid
        supplementary = [g for g in os.getgrouplist("labgen-linux-runner", gid) if g != gid]
        assert supplementary == []


class TestResolveRunnerIdentityFailClosed:
    def test_missing_user_raises_not_falls_back(self):
        with pytest.raises(RunnerIdentityError) as exc_info:
            resolve_runner_identity("definitely-not-a-real-user-xyz", "labgen-linux-runner")
        assert exc_info.value.reason == "runner_user_missing"

    def test_missing_group_raises(self, monkeypatch):
        # Real user, but ask for a group that doesn't exist.
        with pytest.raises(RunnerIdentityError) as exc_info:
            resolve_runner_identity("labgen-linux-runner", "definitely-not-a-real-group-xyz")
        assert exc_info.value.reason == "runner_group_missing"

    def test_uid_zero_raises(self, monkeypatch):
        class _FakePwent:
            pw_uid = 0

        monkeypatch.setattr(pwd, "getpwnam", lambda name: _FakePwent())
        with pytest.raises(RunnerIdentityError) as exc_info:
            resolve_runner_identity("root", "labgen-linux-runner")
        assert exc_info.value.reason == "runner_uid_is_root"

    def test_gid_zero_raises(self, monkeypatch):
        class _FakePwent:
            pw_uid = 997

        class _FakeGrent:
            gr_gid = 0

        monkeypatch.setattr(pwd, "getpwnam", lambda name: _FakePwent())
        monkeypatch.setattr(grp, "getgrnam", lambda name: _FakeGrent())
        with pytest.raises(RunnerIdentityError) as exc_info:
            resolve_runner_identity("labgen-linux-runner", "root")
        assert exc_info.value.reason == "runner_gid_is_root"

    def test_supplementary_groups_raise(self, monkeypatch):
        class _FakePwent:
            pw_uid = 997

        class _FakeGrent:
            gr_gid = 997

        monkeypatch.setattr(pwd, "getpwnam", lambda name: _FakePwent())
        monkeypatch.setattr(grp, "getgrnam", lambda name: _FakeGrent())
        monkeypatch.setattr(os, "getgrouplist", lambda name, gid: [997, 27])  # 27 = sudo, e.g.
        with pytest.raises(RunnerIdentityError) as exc_info:
            resolve_runner_identity("labgen-linux-runner", "labgen-linux-runner")
        assert exc_info.value.reason == "runner_has_supplementary_groups"

    def test_no_fallback_uid_on_any_failure(self, monkeypatch):
        """Never returns a partial/default identity on error — the caller
        must only ever see either a fully-validated RunnerIdentity or an
        exception, nothing in between that could be misread as 'use root'."""
        monkeypatch.setattr(
            pwd, "getpwnam", lambda name: (_ for _ in ()).throw(KeyError(name))
        )
        with pytest.raises(RunnerIdentityError):
            result = resolve_runner_identity("nope", "nope")
            assert result is None  # unreachable if raise works correctly
