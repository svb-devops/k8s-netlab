"""
Regression test for a safety-reviewer finding on the Linux privilege
separation work: LinuxRehearsalService's default constructor path used to
silently build a root-running LinuxRuntimeAdapter when `adapter=` was
omitted — the exact "silently falls back to root" trap the rest of this
Sprint's fail-closed design (routes.get_linux_runtime_adapter(),
routes.get_linux_rehearsal_service()) was built to avoid. No production call
site relied on this default (routes.py always passed a resolved adapter),
but nothing stopped a future caller from hitting it by omission.

Fix: the default path (adapter=None) now requires runner_uid=/runner_gid=
explicitly and raises ValueError otherwise — there is no way to construct a
root-running LinuxRehearsalService by simply forgetting a parameter.
"""

import pytest

pytestmark = pytest.mark.static


class TestLinuxRehearsalServiceNoSilentRoot:

    def test_missing_adapter_and_runner_identity_raises(self):
        from backend.labgen.linux_rehearsal_service import LinuxRehearsalService

        with pytest.raises(ValueError, match="no default that runs .* as root"):
            LinuxRehearsalService(session_repo=object(), draft_repo=object())

    def test_missing_adapter_with_only_runner_uid_raises(self):
        from backend.labgen.linux_rehearsal_service import LinuxRehearsalService

        with pytest.raises(ValueError):
            LinuxRehearsalService(session_repo=object(), draft_repo=object(), runner_uid=997)

    def test_missing_adapter_with_only_runner_gid_raises(self):
        from backend.labgen.linux_rehearsal_service import LinuxRehearsalService

        with pytest.raises(ValueError):
            LinuxRehearsalService(session_repo=object(), draft_repo=object(), runner_gid=997)

    def test_explicit_runner_identity_without_adapter_succeeds(self):
        from backend.labgen.linux_rehearsal_service import LinuxRehearsalService
        from backend.labgen.linux_runner_identity import resolve_runner_identity

        identity = resolve_runner_identity("labgen-linux-runner", "labgen-linux-runner")
        svc = LinuxRehearsalService(
            session_repo=object(),
            draft_repo=object(),
            runner_uid=identity.uid,
            runner_gid=identity.gid,
        )
        assert svc._adapter._cmd_executor._runner_uid == identity.uid
        assert svc._adapter._cmd_executor._runner_uid != 0

    def test_explicit_adapter_still_works_without_runner_identity(self):
        # Back-compat: existing tests pass a pre-built adapter= directly.
        from backend.labgen.linux_rehearsal_service import LinuxRehearsalService
        from backend.labgen.linux_runtime_adapter import LinuxRuntimeAdapter

        adapter = LinuxRuntimeAdapter(enabled=True)
        svc = LinuxRehearsalService(session_repo=object(), draft_repo=object(), adapter=adapter)
        assert svc._adapter is adapter
