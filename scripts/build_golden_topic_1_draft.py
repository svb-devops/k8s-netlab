"""
One-off script: construct the Golden Topic #1 lab draft (chmod correct, still
Permission Denied) and register it in the LabDraft repository as publish_status
DRAFT (never published, never added to any public allowlist).

Run once: python3 scripts/build_golden_topic_1_draft.py
Idempotent: re-running with the same lab_id overwrites via repository.update()
if the draft already exists (checked at the top), so it is safe to re-run
after adjustments during rehearsal debugging.
"""
from __future__ import annotations

from backend.labgen.models import (
    CleanupLinuxWorkspace,
    ExplainField,
    LabDomainType,
    LabDraft,
    LinuxSandboxPolicy,
    LinuxVerifyTemplate,
    LinuxVerifyType,
    PublishStatus,
    RuntimeRequirements,
    Step,
)
from backend.labgen.repository import LabDraftRepository

LAB_ID = "a1c3f7e2-9b6d-4e12-8f4a-6d2c5e0b7a91"


def _explain(concept: str, observation: str) -> ExplainField:
    return ExplainField(concept=concept, observation=observation)


def build_draft() -> LabDraft:
    steps = [
        Step(
            step_id="cpd-step-1",
            order=1,
            why=(
                "A file's own permission bits are only half of the access story. "
                "Reproducing the incident from scratch — including the exact "
                "sequence a prior deploy script ran — builds the instinct to "
                "check reality (a real read attempt) before trusting a mode string."
            ),
            do=(
                "Create case/ and case/vault/, write the incident note and "
                "report.txt, then replay the exact permission sequence from the "
                "incident: set report.txt to 644 (correct) and vault to 600 "
                "(the actual misconfiguration). Then try to read report.txt."
            ),
            commands=[
                "mkdir -p case",
                "mkdir -p case/vault",
                "echo 'Deployment log: report.txt permission bits were reset to 644 during the incident response yesterday.' > case/incident-note.txt",
                "echo 'Q3 onboarding summary: pending review, ticket 4471.' > case/vault/report.txt",
                "chmod 644 case/vault/report.txt",
                "chmod 600 case/vault",
                "cat case/incident-note.txt",
                "cat case/vault/report.txt",
            ],
            observe=(
                "case/incident-note.txt reads fine. The final `cat case/vault/report.txt` "
                "fails with a real 'Permission denied' — even though the file's own mode "
                "(644) looks completely reasonable."
            ),
            explain=_explain(
                concept=(
                    "Reading a file requires two independent permission checks: read "
                    "permission on the file itself, AND execute (traverse) permission on "
                    "every directory in the path leading to it. report.txt's own bits "
                    "(644) are correct, but case/vault/ itself is 600 — no execute bit "
                    "for anyone, so nothing can even reach the file, regardless of the "
                    "file's own mode."
                ),
                observation=(
                    "Run `stat -c %a case/vault/report.txt` to confirm the file's own "
                    "mode really is 644. If it isn't, re-run the chmod command from Step 1."
                ),
            ),
            verify=[],
            linux_verify=[
                LinuxVerifyTemplate(
                    verify_id="cpd-s1-v1",
                    type=LinuxVerifyType.LINUX_FILE_MODE_MATCHES,
                    target_path="case/vault/report.txt",
                    expected_mode="644",
                    description="report.txt's own mode is already correct (644)",
                    failure_hint="Run: chmod 644 case/vault/report.txt",
                ),
                LinuxVerifyTemplate(
                    verify_id="cpd-s1-v2",
                    type=LinuxVerifyType.LINUX_PATH_ACCESS_CONDITION,
                    target_path="case/vault/report.txt",
                    access_operation="read_file",
                    expected_access=False,
                    expected_errno="EACCES",
                    description="Real read access to report.txt is currently denied",
                    failure_hint="Confirm case/vault is mode 600: stat -c %a case/vault",
                ),
            ],
            troubleshoot=(
                "If `cat case/vault/report.txt` unexpectedly succeeds, case/vault may "
                "not actually be 600 — re-run `chmod 600 case/vault` and retry."
            ),
        ),
        Step(
            step_id="cpd-step-2",
            order=2,
            why=(
                "The most natural first instinct when 'Permission denied' shows up is "
                "to re-chmod the file. Proving that doesn't help — on a file whose mode "
                "is already correct — is what forces the search further up the path."
            ),
            do=(
                "Re-run chmod 644 on report.txt (a no-op — it is already 644) and "
                "confirm the read still fails exactly the same way."
            ),
            commands=[
                "chmod 644 case/vault/report.txt",
                "cat case/vault/report.txt",
            ],
            observe=(
                "The chmod succeeds silently (mode was already 644). The read still "
                "fails with Permission denied — proving report.txt's own mode was never "
                "the problem."
            ),
            explain=_explain(
                concept=(
                    "chmod only ever changes the mode bits of the path you name. It "
                    "cannot affect any other directory in the path. If the failure "
                    "persists after confirming the target's own mode is correct, the "
                    "root cause is structurally somewhere else — a parent directory."
                ),
                observation=(
                    "If this step's read now succeeds, something else in the environment "
                    "changed case/vault's mode — check with `stat -c %a case/vault`."
                ),
            ),
            verify=[],
            linux_verify=[
                LinuxVerifyTemplate(
                    verify_id="cpd-s2-v1",
                    type=LinuxVerifyType.LINUX_FILE_MODE_MATCHES,
                    target_path="case/vault/report.txt",
                    expected_mode="644",
                    description="report.txt mode is still 644 after the no-op chmod",
                    failure_hint="Run: chmod 644 case/vault/report.txt",
                ),
                LinuxVerifyTemplate(
                    verify_id="cpd-s2-v2",
                    type=LinuxVerifyType.LINUX_PATH_ACCESS_CONDITION,
                    target_path="case/vault/report.txt",
                    access_operation="read_file",
                    expected_access=False,
                    expected_errno="EACCES",
                    description="Read access is STILL denied — re-chmod'ing the file did not help",
                    failure_hint="This is expected — the root cause is not the file's own mode",
                ),
            ],
            troubleshoot="",
        ),
        Step(
            step_id="cpd-step-3",
            order=3,
            why=(
                "Walking the directory chain with ls/stat — rather than guessing — is "
                "the actual diagnostic skill this lab teaches. Directory execute bits "
                "are easy to overlook because `ls -l` output for a directory looks "
                "structurally identical to a file's, but means something different."
            ),
            do=(
                "Inspect the permissions of case/ and case/vault/ directly. Identify "
                "which one is missing the execute (traverse) bit."
            ),
            commands=[
                "ls -la case",
                "stat case",
                "stat case/vault",
            ],
            observe=(
                "case/ shows normal directory permissions (755-class, execute bit "
                "present). case/vault/ shows 600 — read/write but no execute bit for "
                "anyone, including its own owner."
            ),
            explain=_explain(
                concept=(
                    "For a directory, the execute bit means 'may traverse into this "
                    "directory' — it has nothing to do with running programs. Without "
                    "it, nothing can resolve any path underneath, no matter how "
                    "permissive the contents' own modes are."
                ),
                observation=(
                    "If both directories look fine here, re-run Step 1's `chmod 600 "
                    "case/vault` — the fixture may not have been created correctly."
                ),
            ),
            verify=[],
            linux_verify=[],
            troubleshoot="",
        ),
        Step(
            step_id="cpd-step-4",
            order=4,
            why=(
                "Fixing only the actual root cause — never widening permissions beyond "
                "what's needed, never touching the file that was never wrong — is the "
                "professional habit this lab is really teaching."
            ),
            do=(
                "Restore case/vault's execute bit with chmod 700 (not 777 — this "
                "workspace is single-owner, there is no reason to grant group/other "
                "access). Confirm the read now succeeds."
            ),
            commands=[
                "chmod 700 case/vault",
                "cat case/vault/report.txt",
            ],
            observe=(
                "The read now succeeds and prints the report.txt content — access is "
                "restored by fixing the parent directory, without ever touching "
                "report.txt's own (always-correct) mode."
            ),
            explain=_explain(
                concept=(
                    "700 grants the owner read+write+execute and denies group/other "
                    "entirely — the minimal fix for a single-owner sandbox workspace. "
                    "chmod 777 would also have 'worked' but grants unnecessary "
                    "world-write access — never the right answer even when it happens "
                    "to unblock you."
                ),
                observation=(
                    "If the read still fails, confirm case/vault's mode with `stat -c %a "
                    "case/vault` — it must show 700, not 600."
                ),
            ),
            verify=[],
            linux_verify=[
                LinuxVerifyTemplate(
                    verify_id="cpd-s4-v1",
                    type=LinuxVerifyType.LINUX_FILE_MODE_MATCHES,
                    target_path="case/vault",
                    expected_mode="700",
                    description="case/vault now has its execute bit restored (700)",
                    failure_hint="Run: chmod 700 case/vault",
                ),
                LinuxVerifyTemplate(
                    verify_id="cpd-s4-v2",
                    type=LinuxVerifyType.LINUX_PATH_ACCESS_CONDITION,
                    target_path="case/vault/report.txt",
                    access_operation="read_file",
                    expected_access=True,
                    description="Real read access to report.txt is now restored",
                    failure_hint="Confirm case/vault is mode 700, not 600",
                ),
            ],
            troubleshoot=(
                "Never use chmod 777 to 'fix' this — it works by accident and grants "
                "far more access than the task requires."
            ),
        ),
    ]

    return LabDraft(
        lab_id=LAB_ID,
        source_article_id="article-linux-chmod-permission-denied-001",
        title="chmod 权限位正确，为什么还是 Permission Denied？",
        description=(
            "A hands-on Linux permission-debugging lab: report.txt's own mode is "
            "already correct (644), yet reading it fails with real Permission denied. "
            "Trace the actual root cause — a parent directory missing its execute bit "
            "— and fix only that, in an isolated non-root sandbox workspace."
        ),
        estimated_duration_minutes=10,
        prerequisites=[
            "Basic familiarity with ls, cat, and chmod",
            "After this lab you will understand: the difference between a file's own "
            "read/write permission and a directory's execute/traverse permission, and "
            "why re-chmod'ing an already-correct file cannot fix a parent-directory "
            "permission problem",
        ],
        target_domain=LabDomainType.LINUX,
        runtime_requirements=RuntimeRequirements(),
        steps=steps,
        linux_sandbox_policy=LinuxSandboxPolicy(
            workspace_root="/home/learner/workspace",
            working_directory="/home/learner/workspace",
        ),
        linux_cleanup=CleanupLinuxWorkspace(
            workspace_root="/home/learner/workspace",
            cleanup_paths=["/home/learner/workspace"],
        ),
        publish_status=PublishStatus.DRAFT,
    )


def main() -> None:
    repo = LabDraftRepository()
    existing = repo.get(LAB_ID)
    draft = build_draft()
    if existing is None:
        repo.create(draft)
        print(f"Created draft {LAB_ID}")
    else:
        repo.update(draft)
        print(f"Updated draft {LAB_ID}")


if __name__ == "__main__":
    main()
