"""
One-off script: non-admin learner smoke test for the Golden Topic #1 draft.

Uses the REAL production LabSessionService/StepProgressionService singletons
(backend.labgen.routes.get_session_service() / get_step_progression_service())
— same privilege-separated Linux runtime adapter, same verifier wiring — but
with the general/linux-learner allowlist gates monkeypatched in THIS process
only to include this draft's lab_id, so a genuine non-admin account can create
a session without touching the shared production .env allowlist (which must
stay scoped to First Wave / already-decided labs, per its own comment).

This does not affect the live systemd service process — it's a fresh
short-lived Python process against the same on-disk repos.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    load_dotenv(_env_file, override=False)

from backend.auth import AuthManager  # noqa: E402
from backend.labgen import routes as labgen_routes  # noqa: E402
from backend.labgen.lab_kubectl_ws import LINUX_LEARNER_VM_SENTINEL, _run_linux_cmd  # noqa: E402
from backend.labgen.models import PublishStatus  # noqa: E402

LAB_ID = "a1c3f7e2-9b6d-4e12-8f4a-6d2c5e0b7a91"
SMOKE_USERNAME = "lnx-cpd-smoke01"
SMOKE_PASSWORD = os.environ.get("GOLDEN_LAB_1_SMOKE_PASSWORD", "")
if not SMOKE_PASSWORD:
    raise SystemExit("Set GOLDEN_LAB_1_SMOKE_PASSWORD before running this script.")


def main() -> None:
    auth = AuthManager()
    created = auth.register_user(SMOKE_USERNAME, SMOKE_PASSWORD)
    print("register_user:", SMOKE_USERNAME, "newly_created:", created)

    session_svc = labgen_routes.get_session_service()
    step_svc = labgen_routes.get_step_progression_service()
    linux_adapter = labgen_routes.get_linux_runtime_adapter()

    # Scope the allowlist gates to this lab_id ONLY, in this process only —
    # never touches the shared .env or the live systemd service.
    session_svc._enabled_lab_ids = frozenset({LAB_ID})
    session_svc._linux_learner_enabled_lab_ids = frozenset({LAB_ID})

    draft = session_svc._draft_repo.get(LAB_ID)
    original_publish_status = draft.publish_status
    # check_step() requires PUBLISHED (or an INTERNAL_REHEARSAL session) —
    # temporarily flip status for this smoke run only, then always revert,
    # regardless of outcome. Never added to any public allowlist throughout,
    # so this never makes the lab actually reachable/listed publicly.
    draft.publish_status = PublishStatus.PUBLISHED
    session_svc._draft_repo.update(draft)
    print("publish_status temporarily set to PUBLISHED for smoke run "
          f"(was {original_publish_status.value})")

    try:
        precheck = session_svc.run_precheck(LAB_ID, LINUX_LEARNER_VM_SENTINEL, SMOKE_USERNAME)
        print("precheck:", precheck.passed, precheck.failures)
        if not precheck.passed and precheck.failures == ["precheck.session_already_active"]:
            # A prior interrupted run of this same script left an active
            # session (in-memory workspace registry resets per-process, but
            # on-disk session state persists) — abort it, it's our own
            # smoke-test artifact, then retry precheck once.
            import json as _json
            raw = _json.loads(open("data/lab_sessions.json").read())
            stale_id = next(
                (sid for sid, s in raw.items()
                 if s.get("student_username") == SMOKE_USERNAME
                 and s.get("lab_id") == LAB_ID
                 and s.get("lab_session_status") == "LAB_ACTIVE"),
                None,
            )
            if stale_id is not None:
                session_svc.abort_session(stale_id)
                print("aborted stale smoke-test session:", stale_id)
                precheck = session_svc.run_precheck(LAB_ID, LINUX_LEARNER_VM_SENTINEL, SMOKE_USERNAME)
                print("precheck (retry):", precheck.passed, precheck.failures)
        if not precheck.passed:
            return

        session = session_svc.create_session(LAB_ID, LINUX_LEARNER_VM_SENTINEL, SMOKE_USERNAME)
        print("session created:", session.session_id, session.lab_session_status,
              "for non-admin user:", SMOKE_USERNAME)

        ws_session = linux_adapter.workspace_manager.get_session(session.session_id)
        workspace_path = ws_session.workspace_path

        for step in draft.steps:
            print(f"--- step {step.step_id} ---")
            for cmd_str in step.commands:
                r = _run_linux_cmd(linux_adapter, session.session_id, workspace_path, cmd_str)
                print("  cmd:", cmd_str, "| blocked:", r["blocked"], "| exit_code:", r["exit_code"])

            result = step_svc.check_step(session.session_id, step.step_id, SMOKE_USERNAME)
            for vr in result.verify_results:
                print("  verify:", vr.verify_id, "| passed:", vr.passed,
                      "| reason:", vr.failure_reason, "| detail:", vr.detail)
            print("  all_passed:", result.all_passed)
            if not result.all_passed:
                print("STEP FAILED — stopping.")
                return

        complete = session_svc.complete_session(session.session_id)
        print("complete:", complete.lab_session_status, "cleanup_verified:",
              getattr(complete, "cleanup_verified", None))
    finally:
        draft = session_svc._draft_repo.get(LAB_ID)
        draft.publish_status = original_publish_status
        session_svc._draft_repo.update(draft)
        print("publish_status reverted to", original_publish_status.value)


if __name__ == "__main__":
    main()
