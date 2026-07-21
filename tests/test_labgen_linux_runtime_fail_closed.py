"""
Regression tests for routes.get_linux_runtime_adapter()'s fail-closed
behavior when the Linux sandbox runner identity cannot be resolved.

Bug this prevents: silently falling back to executing learner commands as
the root API process if the labgen-linux-runner system account is missing,
misconfigured, or accidentally granted supplementary groups — which is
exactly the privilege-escalation-adjacent bug this whole Sprint exists to
close (see LINUX_GOLDEN_TOPIC_1_RUNTIME_BLOCKED_v0.1.md).
"""

import pytest

from backend.labgen import routes as labgen_routes

pytestmark = pytest.mark.static


@pytest.fixture(autouse=True)
def _reset_linux_runtime_singleton(monkeypatch):
    """The adapter and identity-error state are module-level singletons —
    reset them around every test so tests don't leak state into each other."""
    monkeypatch.setattr(labgen_routes, "_linux_runtime_adapter", None)
    monkeypatch.setattr(labgen_routes, "_linux_runtime_identity_error", None)
    yield
    monkeypatch.setattr(labgen_routes, "_linux_runtime_adapter", None)
    monkeypatch.setattr(labgen_routes, "_linux_runtime_identity_error", None)


class TestGetLinuxRuntimeAdapterFailClosed:

    def test_returns_none_when_no_labs_enabled(self, monkeypatch):
        monkeypatch.setattr(labgen_routes.config, "LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS", frozenset())
        assert labgen_routes.get_linux_runtime_adapter() is None
        assert labgen_routes.get_linux_runtime_identity_error() is None

    def test_returns_none_and_records_error_when_runner_user_missing(self, monkeypatch):
        monkeypatch.setattr(
            labgen_routes.config, "LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS", frozenset({"some-lab-id"})
        )
        monkeypatch.setattr(labgen_routes.config, "LABGEN_LINUX_RUNNER_USER", "definitely-not-real-xyz")
        monkeypatch.setattr(labgen_routes.config, "LABGEN_LINUX_RUNNER_GROUP", "labgen-linux-runner")

        adapter = labgen_routes.get_linux_runtime_adapter()

        assert adapter is None
        error = labgen_routes.get_linux_runtime_identity_error()
        assert error is not None
        assert "definitely-not-real-xyz" in error

    def test_does_not_retry_resolution_once_failed_this_process(self, monkeypatch):
        # Guards against a subtle bug: if resolution failed once, a later
        # call must not silently retry and potentially succeed with a
        # different config value read mid-flight — the failure is sticky
        # for this process, matching "fail closed" (not "fail closed until
        # someone calls it again").
        monkeypatch.setattr(
            labgen_routes.config, "LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS", frozenset({"some-lab-id"})
        )
        monkeypatch.setattr(labgen_routes.config, "LABGEN_LINUX_RUNNER_USER", "definitely-not-real-xyz")

        labgen_routes.get_linux_runtime_adapter()
        first_error = labgen_routes.get_linux_runtime_identity_error()

        # Even if the config now looks fixed, a within-process retry should
        # not happen automatically (a real restart is required, matching how
        # the rest of config.py's module-level values are load-once).
        monkeypatch.setattr(labgen_routes.config, "LABGEN_LINUX_RUNNER_USER", "labgen-linux-runner")
        adapter = labgen_routes.get_linux_runtime_adapter()

        assert adapter is None
        assert labgen_routes.get_linux_runtime_identity_error() == first_error

    def test_returns_real_adapter_wired_with_resolved_runner_identity(self, monkeypatch):
        monkeypatch.setattr(
            labgen_routes.config, "LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS", frozenset({"some-lab-id"})
        )
        monkeypatch.setattr(labgen_routes.config, "LABGEN_LINUX_RUNNER_USER", "labgen-linux-runner")
        monkeypatch.setattr(labgen_routes.config, "LABGEN_LINUX_RUNNER_GROUP", "labgen-linux-runner")

        adapter = labgen_routes.get_linux_runtime_adapter()

        assert adapter is not None
        assert labgen_routes.get_linux_runtime_identity_error() is None
        # The adapter's command executor must have a non-root runner identity
        # wired in — not the default None (which would mean root execution).
        assert adapter._cmd_executor._runner_uid is not None
        assert adapter._cmd_executor._runner_uid != 0
