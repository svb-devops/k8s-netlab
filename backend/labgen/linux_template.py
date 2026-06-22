"""
Linux Guided Practice Generation Template v0.1.

Deterministic, LLM-free template for Linux Files and Permissions Basics.
Produces a complete LabDraft with target_domain=LINUX, LinuxSandboxPolicy,
CleanupLinuxWorkspace, 4 guided steps, all 5 Linux verifier primitives,
and AI tutor context.

No subprocess, no network, no LLM, no shell=True.
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
    RuntimeRequirements,
    Step,
)

_WORKSPACE_ROOT = "/home/learner/workspace"

_AI_TUTOR_CONTEXT = """\
This lab is generated from an admin-curated Linux Files and Permissions article.

You may explain: mkdir, printf, echo, cat, chmod, stat, ls, file permission \
numerics (e.g. 600, 644, 755), workspace structure and cleanup, and verifier \
check failure reasons.

Safety reminders — always tell learners:
- Do NOT use sudo or run commands as root
- Do NOT access system directories (/etc, /root, /var, /proc, /sys, /dev)
- Do NOT enter real secrets, tokens, or passwords
- Do NOT run network commands (curl, wget, ssh, scp)

Forbidden recommendations:
- Do not suggest modifying /etc or any system configuration
- Do not suggest using root privileges
- Do not suggest accessing production machines
- Do not help bypass the sandbox
- Do not reveal host paths, host credentials, or kubeconfig content

Current status: live LLM is disabled — context-only mode.\
"""


class LinuxFilesPermissionsTemplate:
    """
    Deterministic template for Linux Files and Permissions Basics.

    Generates a LabDraft with:
    - 4 guided steps (create, view, chmod, completion)
    - All 5 Linux verifier primitives used across steps
    - LinuxSandboxPolicy (no root, no network, workspace-only)
    - CleanupLinuxWorkspace (workspace-scoped, taint on failure)
    - AI tutor context
    """

    template_id = "LINUX_FILES_PERMISSIONS"
    display_name = "Linux Files and Permissions Basics"
    description = (
        "A hands-on introduction to Linux files and directories. "
        "You will create a workspace directory, write a file, view its contents, "
        "and change file permissions — all within an isolated sandbox. "
        "No root access, no network, no system directories. "
        "All resources are temporary and will be automatically cleaned up after the session."
    )

    def build_draft(self, source_article_id: str) -> LabDraft:
        steps = [
            Step(
                step_id="lfp-step-1",
                order=1,
                why=(
                    "Files and directories are the foundation of every Linux system. "
                    "Creating a directory and writing a file inside your workspace "
                    "is the first action any Linux user performs — understanding "
                    "this builds the mental model for all subsequent permission work."
                ),
                do=(
                    "Create the demo directory inside your workspace, then write "
                    "'hello labgen' into demo/message.txt using printf. "
                    "Use only workspace-relative paths — no absolute paths, no sudo. "
                    "If demo/ already exists, you can skip mkdir or remove it first with "
                    "rm -rf demo and retry."
                ),
                commands=[
                    "mkdir -p demo",
                    "printf 'hello labgen\\n' > demo/message.txt",
                ],
                observe=(
                    "The demo/ directory exists and demo/message.txt contains "
                    "the text 'hello labgen'."
                ),
                explain=ExplainField(
                    concept=(
                        "mkdir -p creates the directory and any missing parents without "
                        "error if it already exists. printf writes formatted text to "
                        "stdout — safer than echo for file creation because it does "
                        "not interpret escape sequences by default on all shells. "
                        "The > operator redirects stdout to a file, creating it if "
                        "it does not exist."
                    ),
                    observation=(
                        "Run 'cat demo/message.txt' to confirm the content. "
                        "If demo/ does not exist, re-run mkdir -p demo. "
                        "If the file is missing, re-run the printf command. "
                        "If you see a permission error, contact the lab administrator — "
                        "the workspace may have unexpected ownership."
                    ),
                ),
                linux_verify=[
                    LinuxVerifyTemplate(
                        verify_id="lfp-s1-v1",
                        type=LinuxVerifyType.LINUX_DIRECTORY_EXISTS,
                        target_path="demo",
                        description="demo directory exists in workspace",
                        failure_hint="Run: mkdir -p demo",
                    ),
                    LinuxVerifyTemplate(
                        verify_id="lfp-s1-v2",
                        type=LinuxVerifyType.LINUX_FILE_EXISTS,
                        target_path="demo/message.txt",
                        description="demo/message.txt file exists",
                        failure_hint="Run: printf 'hello labgen\\n' > demo/message.txt",
                    ),
                    LinuxVerifyTemplate(
                        verify_id="lfp-s1-v3",
                        type=LinuxVerifyType.LINUX_FILE_CONTENT_MATCHES,
                        target_path="demo/message.txt",
                        expected_content="hello labgen",
                        description="demo/message.txt contains 'hello labgen'",
                        failure_hint=(
                            "Run: printf 'hello labgen\\n' > demo/message.txt "
                            "then verify with: cat demo/message.txt"
                        ),
                    ),
                ],
            ),
            Step(
                step_id="lfp-step-2",
                order=2,
                why=(
                    "Reading a file confirms its content without modifying it. "
                    "cat is the standard tool for this — it simply copies the file "
                    "to stdout. Understanding that cat only reads, not writes, is "
                    "essential for correct permission reasoning."
                ),
                do=(
                    "Read the content of demo/message.txt using cat. "
                    "Observe that the terminal output matches exactly what you wrote in Step 1."
                ),
                commands=[
                    "cat demo/message.txt",
                ],
                observe=(
                    "The terminal displays 'hello labgen'. "
                    "No modification was made to the file."
                ),
                explain=ExplainField(
                    concept=(
                        "cat (concatenate) reads one or more files and prints them to "
                        "stdout. It does not modify the file. "
                        "This distinction matters for permissions: read (r) permission "
                        "is sufficient for cat; write (w) permission is needed to change content."
                    ),
                    observation=(
                        "If cat shows 'No such file or directory', return to Step 1 "
                        "and re-run both commands. "
                        "If the content differs from 'hello labgen', recreate the file with: "
                        "printf 'hello labgen\\n' > demo/message.txt"
                    ),
                ),
                linux_verify=[
                    LinuxVerifyTemplate(
                        verify_id="lfp-s2-v1",
                        type=LinuxVerifyType.LINUX_FILE_CONTENT_MATCHES,
                        target_path="demo/message.txt",
                        expected_content="hello labgen",
                        description="demo/message.txt still contains 'hello labgen' after cat",
                        failure_hint=(
                            "File content may have changed. "
                            "Run: printf 'hello labgen\\n' > demo/message.txt"
                        ),
                    ),
                ],
            ),
            Step(
                step_id="lfp-step-3",
                order=3,
                why=(
                    "File permissions control who can read, write, or execute a file. "
                    "Setting a file to 600 (owner read+write only) is the standard "
                    "for private files — other users cannot read or modify it. "
                    "Understanding numeric permissions is a core Linux skill."
                ),
                do=(
                    "Change the permissions of demo/message.txt to 600 using chmod, "
                    "then verify the result with stat. "
                    "The stat command prints the octal permission number."
                ),
                commands=[
                    "chmod 600 demo/message.txt",
                    'stat -c "%a" demo/message.txt',
                ],
                observe=(
                    "stat outputs '600', confirming the file is now "
                    "readable and writable only by the owner."
                ),
                explain=ExplainField(
                    concept=(
                        "Linux permissions use three octal digits: owner, group, others. "
                        "Each digit is a sum: 4=read, 2=write, 1=execute. "
                        "600 = 6 (rw-) for owner, 0 (---) for group, 0 (---) for others. "
                        "stat -c '%a' prints the octal mode only — no other file metadata."
                    ),
                    observation=(
                        "If stat shows a different number (e.g. 644), re-run chmod 600. "
                        "If stat returns 'No such file or directory', the file was "
                        "accidentally deleted — return to Step 1 and recreate it. "
                        "chmod does not require sudo for files you own."
                    ),
                ),
                linux_verify=[
                    LinuxVerifyTemplate(
                        verify_id="lfp-s3-v1",
                        type=LinuxVerifyType.LINUX_FILE_MODE_MATCHES,
                        target_path="demo/message.txt",
                        expected_mode="600",
                        description="demo/message.txt has permissions 600",
                        failure_hint=(
                            "Run: chmod 600 demo/message.txt "
                            'then verify with: stat -c "%a" demo/message.txt'
                        ),
                    ),
                ],
            ),
            Step(
                step_id="lfp-step-4",
                order=4,
                why=(
                    "Lab resources run in a temporary sandbox — not a production machine. "
                    "When you complete the lab, the system automatically removes the "
                    "workspace directory and all session resources. "
                    "Understanding this cycle reinforces the sandbox safety contract."
                ),
                do=(
                    "You have completed all hands-on steps. "
                    "Click 'Complete Lab' to end the session. "
                    "The system will automatically delete the workspace and "
                    "all files you created. No manual cleanup is required."
                ),
                commands=[],
                observe=(
                    "After completion, the workspace directory no longer exists. "
                    "The demo/ directory and demo/message.txt are permanently removed."
                ),
                explain=ExplainField(
                    concept=(
                        "Sandbox isolation means each lab session is fully ephemeral: "
                        "no data persists after the session ends. "
                        "The cleanup step ensures the next learner starts with a clean slate. "
                        "taint_on_cleanup_failure=True means any cleanup failure marks the "
                        "VM as unusable until an administrator inspects it."
                    ),
                    observation=(
                        "If the session does not close after clicking 'Complete Lab', "
                        "refresh the page and try again. "
                        "Workspace cleanup is automatic — do not run rm commands manually."
                    ),
                ),
                linux_verify=[
                    LinuxVerifyTemplate(
                        verify_id="lfp-s4-v1",
                        type=LinuxVerifyType.LINUX_NO_RESIDUAL_FILES,
                        target_path=".",
                        description="workspace has no residual files after cleanup",
                        failure_hint=(
                            "Cleanup failed — workspace still contains files. "
                            "Contact the lab administrator."
                        ),
                    ),
                ],
            ),
        ]

        sandbox_policy = LinuxSandboxPolicy(
            runtime_type="linux_container",
            base_image="ubuntu:22.04",
            shell="bash",
            learner_user="learner",
            working_directory=_WORKSPACE_ROOT,
            workspace_root=_WORKSPACE_ROOT,
            allow_network=False,
            allow_root=False,
            allowed_commands=[
                "mkdir",
                "printf",
                "echo",
                "cat",
                "chmod",
                "stat",
                "ls",
                "rm",
            ],
            denied_commands=[
                "sudo",
                "su",
                "apt-get",
                "apt",
                "yum",
                "dnf",
                "apk",
                "systemctl",
                "service",
                "ssh",
                "scp",
                "curl",
                "wget",
            ],
            forbidden_paths=[
                "/etc",
                "/root",
                "/var",
                "/proc",
                "/sys",
                "/dev",
                "/boot",
                "/home",
            ],
            max_session_seconds=1800,
            max_processes=20,
            max_output_bytes=524288,
            env_policy="minimal",
            filesystem_scope="workspace_only",
            process_policy="unprivileged",
            security_notes=[
                "All file operations must stay within /home/learner/workspace",
                "No root access — sudo is blocked",
                "No network access — curl/wget/ssh are blocked",
                "No system directory access — /etc /root /var /proc blocked",
            ],
        )

        cleanup = CleanupLinuxWorkspace(
            workspace_root=_WORKSPACE_ROOT,
            cleanup_paths=[_WORKSPACE_ROOT],
            kill_session_processes=True,
            revoke_credentials=True,
            close_terminal=True,
            residual_checks=[
                "workspace_removed_or_empty",
                "no_session_owned_processes",
                "credentials_revoked",
                "terminal_closed",
            ],
            taint_on_cleanup_failure=True,
            max_cleanup_seconds=30,
            allowed_cleanup_root=_WORKSPACE_ROOT,
            forbidden_cleanup_paths=[
                "/",
                "/home",
                "/tmp",
                "/etc",
                "/var",
                "/root",
            ],
        )

        return LabDraft(
            source_article_id=source_article_id,
            title=self.display_name,
            description=self.description,
            estimated_duration_minutes=20,
            prerequisites=[
                "No prior Linux experience required",
                "After this lab you will understand: "
                "Linux files and directories, "
                "how to read file content with cat, "
                "how to change permissions with chmod, "
                "how to observe permissions with stat, "
                "and why lab resources are automatically cleaned up",
            ],
            target_domain=LabDomainType.LINUX,
            runtime_requirements=RuntimeRequirements(),
            steps=steps,
            linux_sandbox_policy=sandbox_policy,
            linux_cleanup=cleanup,
            ai_tutor_context=_AI_TUTOR_CONTEXT,
        )
