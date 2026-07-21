"""
One-off script: run a REAL internal rehearsal against the Golden Topic #1
draft, using the exact production service wiring (backend.labgen.routes.
get_linux_rehearsal_service()) — same runner identity, same repos, same
sandbox root the admin rehearsal HTTP endpoint uses in production.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    load_dotenv(_env_file, override=False)

from backend.labgen.routes import get_linux_rehearsal_service  # noqa: E402

LAB_ID = "a1c3f7e2-9b6d-4e12-8f4a-6d2c5e0b7a91"
ADMIN_USERNAME = os.environ.get("REHEARSAL_ADMIN_USERNAME", "admin")


def main() -> None:
    svc = get_linux_rehearsal_service()

    precheck = svc.run_linux_rehearsal_precheck(LAB_ID, ADMIN_USERNAME)
    print("precheck:", precheck.passed, precheck.failures)
    if not precheck.passed:
        return

    session = svc.create_linux_rehearsal_session(LAB_ID, ADMIN_USERNAME)
    print("session created:", session.session_id, session.lab_session_status)

    draft = svc._draft_repo.get(LAB_ID)
    for step in draft.steps:
        result = svc.execute_linux_step(session.session_id, step.step_id)
        print(f"--- step {step.step_id} ---")
        for cr in result.command_results:
            print("  cmd:", cr.cmd, "| ok:", cr.ok, "| rc:", cr.returncode,
                  "| stderr:", cr.stderr[:120] if cr.stderr else "")
        for vr in result.verifier_results:
            print("  verify:", vr.verify_id, "| passed:", vr.passed,
                  "| reason:", vr.failure_reason, "| detail:", vr.detail)
        print("  all_verifiers_passed:", result.all_verifiers_passed,
              "step_index_advanced:", result.step_index_advanced,
              "ready_to_complete:", result.ready_to_complete)
        if not result.all_verifiers_passed:
            print("STEP FAILED — stopping.")
            return

    complete = svc.complete_linux_rehearsal(session.session_id)
    print("complete: cleanup_verified:", complete.cleanup_verified,
          "rehearsal_completed:", complete.rehearsal_completed,
          "session_status:", complete.session.lab_session_status)


if __name__ == "__main__":
    main()
