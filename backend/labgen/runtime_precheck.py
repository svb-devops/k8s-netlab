"""
Runtime Precheck Service — Contract §11 VM_PRECHECK_RUNNING conditions 4 and 6.

Condition 4: No prior namespace stuck in K8s Terminating state for > 5 minutes.
Condition 6: If a prior lab on this VM declared cluster_scoped_resources, its
             cleanup_verified must be True before a new lab may start.

Design constraints:
- Pure read service: no repository writes, no K8s resource creation.
- No audit events emitted here — audit is the caller's responsibility.
- Fail-closed: any unhandled exception in a condition check returns BLOCKED.
- All issue messages pass through _sanitize_message() to strip sensitive data.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, Field

from backend.labgen.failure_reasons import FailureReason

if TYPE_CHECKING:
    from backend.labgen.lab_session_repository import LabSessionRepository
    from backend.labgen.namespace_lifecycle import NamespaceLifecyclePort
    from backend.labgen.repository import LabDraftRepository

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sensitive-data redaction (safety net applied to every issue message)
# ---------------------------------------------------------------------------

_REDACT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Anthropic / OpenAI API keys
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), "[REDACTED]"),
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "[REDACTED]"),
    # Bearer tokens
    (re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+"), "[REDACTED]"),
    # JWT-shaped strings (header starts with eyJ)
    (re.compile(r"eyJ[A-Za-z0-9_=-]{20,}"), "[REDACTED]"),
    # Generic long base64 blobs (≥ 40 chars)
    (re.compile(r"[A-Za-z0-9+/]{40,}={0,2}"), "[REDACTED]"),
    # Labelled secrets / credentials
    (re.compile(r"private[_-]?key\s*[:=]\s*\S+", re.IGNORECASE), "[REDACTED]"),
    (re.compile(r"password\s*[:=]\s*\S+", re.IGNORECASE), "[REDACTED]"),
    (re.compile(r"\bsecret\s*[:=]\s*\S+", re.IGNORECASE), "[REDACTED]"),
    (re.compile(r"\btoken\s*[:=]\s*\S+", re.IGNORECASE), "[REDACTED]"),
    # Python tracebacks
    (re.compile(r"Traceback \(most recent call last\).*", re.DOTALL), "[REDACTED:traceback]"),
]


def _sanitize_message(msg: str) -> str:
    """Strip sensitive patterns from a human-readable message string."""
    for pattern, replacement in _REDACT_PATTERNS:
        msg = pattern.sub(replacement, msg)
    return msg


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class RuntimePrecheckCondition(str, Enum):
    """Stable machine codes for each runtime precheck condition.

    Values must never change after release (breaking change for clients that
    parse them programmatically).
    """

    PRIOR_NAMESPACE_TERMINATING = "prior_namespace_terminating"
    PRIOR_CLUSTER_SCOPED_NOT_CLEANED = "prior_cluster_scoped_not_cleaned"


class RuntimePrecheckStatus(str, Enum):
    PASSED = "passed"
    BLOCKED = "blocked"


class RuntimePrecheckIssue(BaseModel):
    code: str
    message: str
    severity: str = "blocking"
    condition: RuntimePrecheckCondition
    source: str
    path: Optional[str] = None


class RuntimePrecheckResult(BaseModel):
    status: RuntimePrecheckStatus
    passed_conditions: list[RuntimePrecheckCondition] = Field(default_factory=list)
    blocked_conditions: list[RuntimePrecheckCondition] = Field(default_factory=list)
    issues: list[RuntimePrecheckIssue] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))

    @property
    def passed(self) -> bool:
        return self.status == RuntimePrecheckStatus.PASSED


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class RuntimePrecheckService:
    """Checks Contract §11 VM_PRECHECK_RUNNING conditions 4 and 6.

    Injected into LabSessionService and called before any runtime resource
    creation (namespace / rolebinding / verifier credential / VM init).

    Thread-safety: stateless after construction — safe for concurrent calls.
    """

    DEFAULT_TERMINATING_THRESHOLD_SECONDS: int = 300  # 5 minutes per Contract §11

    def __init__(
        self,
        ns_lifecycle: "NamespaceLifecyclePort",
        session_repo: "LabSessionRepository",
        draft_repo: "LabDraftRepository",
        terminating_threshold_seconds: int = DEFAULT_TERMINATING_THRESHOLD_SECONDS,
    ) -> None:
        self._ns = ns_lifecycle
        self._sessions = session_repo
        self._drafts = draft_repo
        self._threshold = terminating_threshold_seconds

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, vm_id: str, student_username: str) -> RuntimePrecheckResult:
        """Run conditions 4 and 6 for the given (vm_id, student_username) pair.

        Returns PASSED when all conditions are satisfied.
        Returns BLOCKED with one RuntimePrecheckIssue per failed condition.
        Never raises — all exceptions are caught and converted to BLOCKED issues.
        """
        issues: list[RuntimePrecheckIssue] = []
        passed: list[RuntimePrecheckCondition] = []
        blocked: list[RuntimePrecheckCondition] = []

        for condition, checker in (
            (RuntimePrecheckCondition.PRIOR_NAMESPACE_TERMINATING, self._check_c4),
            (RuntimePrecheckCondition.PRIOR_CLUSTER_SCOPED_NOT_CLEANED, self._check_c6),
        ):
            issue = checker(vm_id, student_username)
            if issue is None:
                passed.append(condition)
            else:
                blocked.append(condition)
                issues.append(issue)

        return RuntimePrecheckResult(
            status=RuntimePrecheckStatus.BLOCKED if blocked else RuntimePrecheckStatus.PASSED,
            passed_conditions=passed,
            blocked_conditions=blocked,
            issues=issues,
        )

    # ------------------------------------------------------------------
    # Condition 4
    # ------------------------------------------------------------------

    def _check_c4(self, vm_id: str, student_username: str) -> Optional[RuntimePrecheckIssue]:
        """Condition 4: no prior namespace stuck in Terminating > threshold_seconds.

        Queries all sessions for the VM (not the current student) so that stale
        Terminating namespaces from previous owners are also detected.
        """
        try:
            sessions = [
                s for s in self._sessions.list_by_vm_id(vm_id)
                if s.namespace is not None
            ]
            for session in sessions:
                if self._ns.is_namespace_stuck_terminating(session.namespace, self._threshold):
                    return RuntimePrecheckIssue(
                        code=FailureReason.RUNTIME_PRECHECK_CONDITION_4_FAILED.value,
                        message=_sanitize_message(
                            "Prior namespace is stuck in Terminating state"
                        ),
                        condition=RuntimePrecheckCondition.PRIOR_NAMESPACE_TERMINATING,
                        source="namespace_lifecycle",
                        path=f"session/{session.session_id}/namespace",
                    )
        except Exception:
            logger.warning(
                "Condition 4 check raised unexpectedly — blocking fail-closed (vm_id=%s)",
                vm_id,
                exc_info=False,
            )
            return RuntimePrecheckIssue(
                code=FailureReason.RUNTIME_PRECHECK_CONDITION_4_FAILED.value,
                message="Namespace termination status check unavailable",
                condition=RuntimePrecheckCondition.PRIOR_NAMESPACE_TERMINATING,
                source="namespace_lifecycle",
            )
        return None

    # ------------------------------------------------------------------
    # Condition 6
    # ------------------------------------------------------------------

    def _check_c6(self, vm_id: str, student_username: str) -> Optional[RuntimePrecheckIssue]:
        """Condition 6: prior lab with cluster_scoped_resources must have cleanup_verified=True.

        Queries all sessions for the VM (not the current student) so that unverified
        cluster-scoped cleanup from previous owners is detected even after VM reassignment.
        LAB_START_FAILED sessions are excluded — they never deployed runtime resources.
        Sessions without a namespace are excluded — namespace creation never completed.
        Fail-closed when draft cannot be retrieved for a session with cleanup_verified=False.
        """
        from backend.labgen.models import LabSessionStatus

        # LAB_START_FAILED: namespace was never created — no resources to check.
        # LAB_CLOSED: session lifecycle is complete; cleanup either succeeded or was
        #   not needed.  If cleanup_verified=False on a LAB_CLOSED session it means
        #   data was written before the field existed (migration gap) — blocking
        #   permanently would brick the VM.
        _SKIP_STATUSES = {
            LabSessionStatus.LAB_START_FAILED,
            LabSessionStatus.LAB_CLOSED,
        }

        try:
            sessions = [
                s for s in self._sessions.list_by_vm_id(vm_id)
                if s.lab_session_status not in _SKIP_STATUSES
                and s.namespace is not None
            ]
            for session in sessions:
                if session.cleanup_verified:
                    continue

                draft = self._drafts.get(session.lab_id)
                if draft is None:
                    return RuntimePrecheckIssue(
                        code=FailureReason.RUNTIME_PRECHECK_CONDITION_6_FAILED.value,
                        message=_sanitize_message(
                            "Prior lab cleanup status cannot be verified: draft not found"
                        ),
                        condition=RuntimePrecheckCondition.PRIOR_CLUSTER_SCOPED_NOT_CLEANED,
                        source="draft_repository",
                        path=f"session/{session.session_id}/lab_id",
                    )

                if (
                    draft.cleanup is not None
                    and draft.cleanup.cluster_scoped_resources
                ):
                    return RuntimePrecheckIssue(
                        code=FailureReason.RUNTIME_PRECHECK_CONDITION_6_FAILED.value,
                        message=_sanitize_message(
                            "Prior lab with cluster-scoped resources has unverified cleanup"
                        ),
                        condition=RuntimePrecheckCondition.PRIOR_CLUSTER_SCOPED_NOT_CLEANED,
                        source="draft_repository",
                        path=f"session/{session.session_id}/cleanup_verified",
                    )
        except Exception:
            logger.warning(
                "Condition 6 check raised unexpectedly — blocking fail-closed (vm_id=%s)",
                vm_id,
                exc_info=False,
            )
            return RuntimePrecheckIssue(
                code=FailureReason.RUNTIME_PRECHECK_CONDITION_6_FAILED.value,
                message="Prior cluster-scoped cleanup verification unavailable",
                condition=RuntimePrecheckCondition.PRIOR_CLUSTER_SCOPED_NOT_CLEANED,
                source="draft_repository",
            )
        return None
