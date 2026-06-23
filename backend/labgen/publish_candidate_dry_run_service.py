"""
PublishCandidateDryRunService — validates a Linux LabDraft against all publish
candidate gates WITHOUT performing an actual publish.

Calling this service:
  - NEVER modifies draft.publish_status
  - NEVER adds entries to the learner catalog
  - NEVER creates lab sessions
  - Always returns actual_publish_performed=False, learner_catalog_changed=False

Six gates are evaluated in order:
  1. admin_gate               — draft state prereqs for publish candidate
  2. validation_gate          — StaticValidator pass, linux boundary recognized
  3. internal_rehearsal_gate  — rehearsal_completed + closed/verified session found
  4. runtime_verifier_cleanup_gate — Linux-specific schema fields present and valid
  5. content_quality_gate     — no placeholders, quality fields populated
  6. safety_gate              — safety invariants verified

publish_candidate_ready = True iff ALL 6 gates pass.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from backend.labgen.models import (
    BlockingLevel,
    LabDomainType,
    LabSessionState,
    LabSessionStatus,
    LabDraft,
    PublishStatus,
    SessionType,
    ValidatorStatus,
)
from backend.labgen.static_validator import StaticValidator

# ─────────────────────────────────────────────────────────────────────────────
# Safety policy constants (mirrors LinuxSandboxPolicy denied commands/paths)
# ─────────────────────────────────────────────────────────────────────────────

_SAFETY_DENIED_COMMANDS: frozenset[str] = frozenset({
    "sudo", "su", "systemctl", "service",
    "curl", "wget", "nc", "ncat", "netcat",
    "ssh", "scp", "sftp",
    "apt", "apt-get", "yum", "dnf", "apk",
    "pip", "pip3",
    "mount", "umount",
    "fdisk", "mkfs", "dd",
    "reboot", "shutdown", "poweroff", "halt",
    "modprobe", "insmod", "rmmod",
    "kill",
})

_SAFETY_FORBIDDEN_PATH_PREFIXES: tuple[str, ...] = (
    "/etc", "/root", "/var", "/proc", "/sys", "/dev", "/boot",
)

_PLACEHOLDER_PATTERN = re.compile(
    r"\[TODO\]|\[PLACEHOLDER\]|\[FIXME\]|<TODO>|<PLACEHOLDER>",
    re.IGNORECASE,
)

# ─────────────────────────────────────────────────────────────────────────────
# Result models
# ─────────────────────────────────────────────────────────────────────────────


class DryRunCheckResult(BaseModel):
    check_id: str
    passed: bool
    detail: Optional[str] = None


class DryRunGateResult(BaseModel):
    gate_id: str
    passed: bool
    checks: list[DryRunCheckResult] = Field(default_factory=list)


class LinuxPublishCandidateDryRunResult(BaseModel):
    """
    Result of a Linux publish-candidate dry run.

    actual_publish_performed is always False.
    learner_catalog_changed is always False.
    dry_run is always True.
    """

    draft_id: str
    dry_run: bool = True
    actual_publish_performed: bool = False
    learner_catalog_changed: bool = False
    publish_candidate_ready: bool
    linux_publish_boundary_recognized: bool
    gate_results: list[DryRunGateResult]
    recommended_next_step: Optional[str] = None
    checked_at: str = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc).isoformat()
    )


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────


class PublishCandidateDryRunService:
    """
    Evaluates a Linux LabDraft against all publish-candidate gates.

    Usage:
        svc = PublishCandidateDryRunService(validator=StaticValidator())
        sessions = session_repo.list_all()
        result = svc.check_linux_publish_candidate(draft, sessions)
    """

    def __init__(self, validator: Optional[StaticValidator] = None) -> None:
        self._validator = validator or StaticValidator()

    def check_linux_publish_candidate(
        self,
        draft: LabDraft,
        sessions: list[LabSessionState],
    ) -> LinuxPublishCandidateDryRunResult:
        """
        Run all 6 gates and return the dry-run result.
        Does NOT modify the draft or catalog.
        """
        gate_results: list[DryRunGateResult] = []

        gate_results.append(self._admin_gate(draft))
        gate_results.append(self._validation_gate(draft))
        gate_results.append(self._internal_rehearsal_gate(draft, sessions))
        gate_results.append(self._runtime_verifier_cleanup_gate(draft))
        gate_results.append(self._content_quality_gate(draft))
        gate_results.append(self._safety_gate(draft))

        publish_candidate_ready = all(g.passed for g in gate_results)
        linux_boundary_recognized = self._linux_boundary_was_recognized(draft)

        recommended = (
            "Linux Article-linked Lab Publish Gate"
            if publish_candidate_ready
            else None
        )

        return LinuxPublishCandidateDryRunResult(
            draft_id=draft.lab_id,
            publish_candidate_ready=publish_candidate_ready,
            linux_publish_boundary_recognized=linux_boundary_recognized,
            gate_results=gate_results,
            recommended_next_step=recommended,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Gate 1 — Admin gate
    # ─────────────────────────────────────────────────────────────────────────

    def _admin_gate(self, draft: LabDraft) -> DryRunGateResult:
        checks: list[DryRunCheckResult] = []

        # Must be Linux domain
        is_linux = draft.target_domain == LabDomainType.LINUX
        checks.append(DryRunCheckResult(
            check_id="admin.target_domain_linux",
            passed=is_linux,
            detail=None if is_linux else f"target_domain is {draft.target_domain!r}, expected LINUX",
        ))

        # Must not already be PUBLISHED
        not_published = draft.publish_status != PublishStatus.PUBLISHED
        checks.append(DryRunCheckResult(
            check_id="admin.not_already_published",
            passed=not_published,
            detail=None if not_published else "draft is already PUBLISHED",
        ))

        # Internal rehearsal must have been completed (admin ran and confirmed)
        checks.append(DryRunCheckResult(
            check_id="admin.rehearsal_completed",
            passed=draft.rehearsal_completed,
            detail=None if draft.rehearsal_completed
            else "rehearsal_completed=False — internal rehearsal must pass before dry run",
        ))

        return DryRunGateResult(
            gate_id="admin_gate",
            passed=all(c.passed for c in checks),
            checks=checks,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Gate 2 — Validation gate
    # ─────────────────────────────────────────────────────────────────────────

    def _validation_gate(self, draft: LabDraft) -> DryRunGateResult:
        checks: list[DryRunCheckResult] = []
        results = self._validator.validate(draft)

        # Separate the expected Linux boundary from unexpected failures
        boundary_found = False
        other_blocking: list[str] = []

        for r in results:
            if r.check_id == "linux.publish_blocked_until_runtime":
                boundary_found = True
                # This is the expected current boundary — not a gate failure
                continue
            if (
                r.status == ValidatorStatus.FAILED
                and r.blocking_level == BlockingLevel.PUBLISH_BLOCKING
            ):
                other_blocking.append(r.check_id)

        # Linux boundary must be present (confirms StaticValidator is working)
        checks.append(DryRunCheckResult(
            check_id="validation.linux_boundary_recognized",
            passed=boundary_found,
            detail=None if boundary_found
            else "linux.publish_blocked_until_runtime not found — unexpected",
        ))

        # No other PUBLISH_BLOCKING failures
        no_other = len(other_blocking) == 0
        checks.append(DryRunCheckResult(
            check_id="validation.no_unexpected_blocking_failures",
            passed=no_other,
            detail=None if no_other
            else f"Unexpected PUBLISH_BLOCKING failures: {other_blocking}",
        ))

        return DryRunGateResult(
            gate_id="validation_gate",
            passed=all(c.passed for c in checks),
            checks=checks,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Gate 3 — Internal rehearsal gate
    # ─────────────────────────────────────────────────────────────────────────

    def _internal_rehearsal_gate(
        self, draft: LabDraft, sessions: list[LabSessionState]
    ) -> DryRunGateResult:
        checks: list[DryRunCheckResult] = []

        # rehearsal_completed flag on draft (authoritative indicator)
        checks.append(DryRunCheckResult(
            check_id="rehearsal.draft_rehearsal_completed",
            passed=draft.rehearsal_completed,
            detail=None if draft.rehearsal_completed
            else "draft.rehearsal_completed=False",
        ))

        # Find a matching closed+verified rehearsal session
        rehearsal_sessions = [
            s for s in sessions
            if s.lab_id == draft.lab_id
            and s.session_type == SessionType.INTERNAL_REHEARSAL
            and s.lab_session_status == LabSessionStatus.LAB_CLOSED
            and s.cleanup_verified
        ]
        has_verified = len(rehearsal_sessions) > 0
        checks.append(DryRunCheckResult(
            check_id="rehearsal.session_closed_and_verified",
            passed=has_verified,
            detail=None if has_verified
            else "No LAB_CLOSED INTERNAL_REHEARSAL session with cleanup_verified=True found",
        ))

        return DryRunGateResult(
            gate_id="internal_rehearsal_gate",
            passed=all(c.passed for c in checks),
            checks=checks,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Gate 4 — Runtime / verifier / cleanup gate
    # ─────────────────────────────────────────────────────────────────────────

    def _runtime_verifier_cleanup_gate(self, draft: LabDraft) -> DryRunGateResult:
        checks: list[DryRunCheckResult] = []

        # linux_sandbox_policy must be present
        has_policy = draft.linux_sandbox_policy is not None
        checks.append(DryRunCheckResult(
            check_id="runtime.linux_sandbox_policy_present",
            passed=has_policy,
            detail=None if has_policy else "linux_sandbox_policy is None",
        ))

        # linux_cleanup must be present
        has_cleanup = draft.linux_cleanup is not None
        checks.append(DryRunCheckResult(
            check_id="runtime.linux_cleanup_present",
            passed=has_cleanup,
            detail=None if has_cleanup else "linux_cleanup is None",
        ))

        # At least one step must have linux_verify entries
        has_verifiers = any(step.linux_verify for step in draft.steps)
        checks.append(DryRunCheckResult(
            check_id="runtime.linux_verifiers_present",
            passed=has_verifiers,
            detail=None if has_verifiers else "No linux_verify entries found in any step",
        ))

        # No K8s verify entries in steps (Linux lab must use linux_verify only)
        k8s_verify_found = any(step.verify for step in draft.steps)
        checks.append(DryRunCheckResult(
            check_id="runtime.no_k8s_verifiers",
            passed=not k8s_verify_found,
            detail=None if not k8s_verify_found
            else "K8s verify entries found in Linux lab steps",
        ))

        return DryRunGateResult(
            gate_id="runtime_verifier_cleanup_gate",
            passed=all(c.passed for c in checks),
            checks=checks,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Gate 5 — Content quality gate
    # ─────────────────────────────────────────────────────────────────────────

    def _content_quality_gate(self, draft: LabDraft) -> DryRunGateResult:
        checks: list[DryRunCheckResult] = []

        # Title must be non-empty and placeholder-free
        title_ok = bool(draft.title) and not _PLACEHOLDER_PATTERN.search(draft.title)
        checks.append(DryRunCheckResult(
            check_id="content.title_present_no_placeholder",
            passed=title_ok,
            detail=None if title_ok else f"title empty or contains placeholder: {draft.title!r}",
        ))

        # Description must be non-empty and placeholder-free
        desc_ok = bool(draft.description) and not _PLACEHOLDER_PATTERN.search(draft.description)
        checks.append(DryRunCheckResult(
            check_id="content.description_present_no_placeholder",
            passed=desc_ok,
            detail=None if desc_ok
            else f"description empty or contains placeholder: {draft.description!r}",
        ))

        # All steps must have at least one command or a why/observe field
        steps_ok = True
        step_failures: list[str] = []
        for i, step in enumerate(draft.steps):
            has_content = bool(step.commands) or bool(step.why) or bool(step.observe)
            if not has_content:
                steps_ok = False
                step_failures.append(f"steps[{i}] has no commands/why/observe")
            # Check for placeholders in step text fields
            for field_name, field_val in [
                ("why", step.why),
                ("observe", step.observe),
            ]:
                if field_val and _PLACEHOLDER_PATTERN.search(field_val):
                    steps_ok = False
                    step_failures.append(
                        f"steps[{i}].{field_name} contains placeholder"
                    )
            # explain is an ExplainField object — check its string sub-fields
            if step.explain:
                for sub_name, sub_val in [
                    ("explain.concept", step.explain.concept),
                    ("explain.observation", step.explain.observation),
                ]:
                    if sub_val and _PLACEHOLDER_PATTERN.search(sub_val):
                        steps_ok = False
                        step_failures.append(f"steps[{i}].{sub_name} contains placeholder")
        checks.append(DryRunCheckResult(
            check_id="content.steps_have_content_no_placeholder",
            passed=steps_ok,
            detail=None if steps_ok else "; ".join(step_failures),
        ))

        # ai_tutor_context must be present and non-empty
        has_tutor = bool(draft.ai_tutor_context)
        checks.append(DryRunCheckResult(
            check_id="content.ai_tutor_context_present",
            passed=has_tutor,
            detail=None if has_tutor else "ai_tutor_context is None or empty",
        ))

        return DryRunGateResult(
            gate_id="content_quality_gate",
            passed=all(c.passed for c in checks),
            checks=checks,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Gate 6 — Safety gate
    # ─────────────────────────────────────────────────────────────────────────

    def _safety_gate(self, draft: LabDraft) -> DryRunGateResult:
        checks: list[DryRunCheckResult] = []

        policy = draft.linux_sandbox_policy

        # allow_root must be False
        root_ok = policy is None or not policy.allow_root
        checks.append(DryRunCheckResult(
            check_id="safety.allow_root_false",
            passed=root_ok,
            detail=None if root_ok else "linux_sandbox_policy.allow_root=True is forbidden",
        ))

        # allow_network must be False
        net_ok = policy is None or not policy.allow_network
        checks.append(DryRunCheckResult(
            check_id="safety.allow_network_false",
            passed=net_ok,
            detail=None if net_ok else "linux_sandbox_policy.allow_network=True is forbidden",
        ))

        # No denied commands in step.commands.
        # Scan ALL tokens (not just the first word) to catch wrappers like
        # "env sudo cmd", "bash -c 'sudo ...'", "$(sudo ...)".
        denied_found: list[str] = []
        for i, step in enumerate(draft.steps):
            for cmd in step.commands:
                tokens = re.split(r"[\s\$\(\)\{\}\;\|\&\`\"\']+", cmd)
                if any(t in _SAFETY_DENIED_COMMANDS for t in tokens if t):
                    denied_found.append(f"steps[{i}]: {cmd!r}")
        checks.append(DryRunCheckResult(
            check_id="safety.no_denied_commands",
            passed=len(denied_found) == 0,
            detail=None if not denied_found else f"Denied commands found: {denied_found}",
        ))

        # No forbidden path prefixes in linux_verify params.
        # Strategy:
        #  - Normalize the raw path (resolves .. and //).
        #  - For absolute paths: block if normalized == prefix or starts with prefix + "/"
        #    (avoids false positives like "/etcmalicious").
        #  - For relative paths: also normalize against a notional workspace root so that
        #    "../etc/passwd" resolves to "/etc/passwd" and is correctly flagged.
        _NOTIONAL_ROOT = "/workspace"
        forbidden_paths: list[str] = []
        for i, step in enumerate(draft.steps):
            for j, lv in enumerate(step.linux_verify):
                raw_path = lv.target_path or ""
                normalized = os.path.normpath(raw_path)
                if not os.path.isabs(normalized):
                    # Treat as relative to a notional workspace dir for boundary check
                    normalized = os.path.normpath(os.path.join(_NOTIONAL_ROOT, raw_path))
                for prefix in _SAFETY_FORBIDDEN_PATH_PREFIXES:
                    if normalized == prefix or normalized.startswith(prefix + "/"):
                        forbidden_paths.append(
                            f"steps[{i}].linux_verify[{j}].target_path={raw_path!r}"
                        )
                        break
        checks.append(DryRunCheckResult(
            check_id="safety.no_forbidden_paths_in_verifiers",
            passed=len(forbidden_paths) == 0,
            detail=None if not forbidden_paths
            else f"Forbidden paths in verifiers: {forbidden_paths}",
        ))

        # LLM call count = 0 is a runtime invariant; verify ai_tutor_context doesn't
        # contain live model call markers (structural check only)
        tutor = draft.ai_tutor_context or ""
        no_live_llm = "LIVE_LLM_ENABLED" not in tutor and "live_enabled=true" not in tutor.lower()
        checks.append(DryRunCheckResult(
            check_id="safety.no_live_llm_marker",
            passed=no_live_llm,
            detail=None if no_live_llm else "ai_tutor_context contains live LLM marker",
        ))

        return DryRunGateResult(
            gate_id="safety_gate",
            passed=all(c.passed for c in checks),
            checks=checks,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _linux_boundary_was_recognized(self, draft: LabDraft) -> bool:
        """
        Returns True if linux.publish_blocked_until_runtime fires for this draft.
        Used to confirm the publish boundary is still in place.
        """
        if draft.target_domain != LabDomainType.LINUX:
            return False
        results = self._validator.validate(draft)
        return any(
            r.check_id == "linux.publish_blocked_until_runtime"
            and r.status == ValidatorStatus.FAILED
            for r in results
        )
