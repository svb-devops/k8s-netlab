"""
StubFeasibilityClassifier — deterministic v0.1 feasibility assessment (no LLM).

Design invariants:
  - Never calls any external API or LLM
  - Always sets evaluated_by=STUB
  - Fail-closed: when in doubt, returns PARTIALLY_LAB_READY + appropriate safety flags
  - Never persists raw article text
  - content_hash is always SHA-256 of the submitted text

Heuristic tiers:
  NOT_LAB_READY: article matches non-operable patterns (pure theory, news, etc.)
                 or contains hard-reject safety flags
  PARTIALLY_LAB_READY: article has some technical content but is missing key criteria
  DIRECTLY_LAB_READY: article has clear commands, verifiable outcome, safe execution
                      (stub is intentionally conservative — only sets this if very clear)
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from backend.labgen.article_models import (
    FeasibilityEvaluatedBy,
    FeasibilityResult,
    FeasibilityStatus,
    SafetyFlag,
    TargetDomain,
    VerifierFeasibility,
)

# Patterns that suggest the article contains secret-like content
_SECRET_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i)(api[_-]?key|access[_-]?key|secret[_-]?key)\s*[:=]\s*\S{10,}"),
    re.compile(r"(?i)password\s*[:=]\s*\S{6,}"),
    re.compile(r"(?i)token\s*[:=]\s*[A-Za-z0-9\-_\.]{20,}"),
    re.compile(r"(?i)private[_-]?key\s*[:=]"),
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)aws_secret_access_key\s*="),
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key ID prefix
]

# Patterns suggesting real-credential dependency
_REAL_CREDENTIAL_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i)(your[_\s]?(real|production|prod)[_\s]?(api[_-]?key|secret|token))"),
    re.compile(r"(?i)replace (this|it) with your (real|actual|production)"),
    re.compile(r"(?i)use your (real|actual|production) (credentials|account|api)"),
]

# Patterns suggesting a production environment is required
_PRODUCTION_ENV_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i)(production|prod)[_\s]environment required"),
    re.compile(r"(?i)requires? (access to )?(prod|production) (cluster|database|server|system)"),
    re.compile(r"(?i)only works? (in|on) (prod|production)"),
]

# Patterns suggesting destructive / dangerous operations
_DESTRUCTIVE_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i)(rm\s+-rf\s+[/~]|dd\s+if=|mkfs\.|format\s+c:)"),
    re.compile(r"(?i)(delete|drop|truncate|wipe)\s+(all|everything|the\s+(entire|whole)\s+database)"),
    re.compile(r"(?i)kubectl\s+delete\s+namespace\s+kube-system"),
    re.compile(r"(?i)(shutdown|poweroff|reboot)\s+--?[a-z]"),
]

# Patterns suggesting K8s domain
_K8S_SIGNALS: list[re.Pattern] = [
    re.compile(r"(?i)(kubectl|kubernetes|k8s|kube|pod|deployment|namespace|configmap|secret|helm|kubeconfig)"),
    re.compile(r"(?i)(apiVersion|kind:\s*(Deployment|Service|Pod|ConfigMap|Secret|Namespace))"),
]

# Patterns suggesting cloud domain (blocked in v0.1)
_CLOUD_SIGNALS: list[re.Pattern] = [
    re.compile(r"(?i)(aws|amazon web services|azure|gcp|google cloud|cloud provider|cloud vendor)"),
    re.compile(r"(?i)(ec2|s3 bucket|lambda function|cloud run|cloud functions|azure vm)"),
]

# Patterns indicating operable content (commands, steps)
_OPERABLE_SIGNALS: list[re.Pattern] = [
    re.compile(r"```[\w]*\n[\s\S]+?```"),  # fenced code blocks
    re.compile(r"(?m)^\$\s+\S"),            # shell prompts
    re.compile(r"(?m)^#\s*\w"),             # headings (step structure)
    re.compile(r"(?i)(step\s+\d+|run the following|execute|apply\s+the)"),
]

# Patterns for non-operable articles
_NON_OPERABLE_SIGNALS: list[re.Pattern] = [
    re.compile(r"(?i)(this article (discusses|explores|introduces|explains|covers))"),
    re.compile(r"(?i)(in conclusion|to summarize|in this blog post)"),
    re.compile(r"(?i)^\s*(opinion|editorial|news|analysis):\s", re.MULTILINE),
]

# Patterns for verifiable K8s outcomes
_VERIFIABLE_K8S_SIGNALS: list[re.Pattern] = [
    re.compile(r"(?i)kubectl (get|describe|apply|create|check)"),
    re.compile(r"(?i)(namespace|configmap|secret|deployment)\s+(should\s+)?(exist|be created|is\s+ready)"),
]


def _has_pattern(text: str, patterns: list[re.Pattern]) -> bool:
    return any(p.search(text) for p in patterns)


def _count_patterns(text: str, patterns: list[re.Pattern]) -> int:
    return sum(1 for p in patterns if p.search(text))


def compute_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class StubFeasibilityClassifier:
    """
    Deterministic stub classifier — v0.1, no LLM.

    Input: raw article text (never persisted after this call)
    Output: FeasibilityResult with evaluated_by=STUB
    """

    def classify(self, text: str) -> FeasibilityResult:
        """
        Classify feasibility of text. Raw text is used here but never stored.
        Call compute_content_hash() separately and store that instead.
        """
        safety_flags: list[SafetyFlag] = []
        reasons: list[str] = []
        missing: list[str] = []
        domain_candidates: list[TargetDomain] = []

        # --- Safety checks (fail-closed) ---
        if _has_pattern(text, _SECRET_PATTERNS):
            safety_flags.append(SafetyFlag.CONTAINS_SECRET_LIKE_CONTENT)
            reasons.append("article appears to contain secret-like content (API keys, tokens, or private keys)")

        if _has_pattern(text, _REAL_CREDENTIAL_PATTERNS):
            safety_flags.append(SafetyFlag.REQUIRES_REAL_CREDENTIALS)
            reasons.append("article references real/production credentials that cannot be substituted")

        if _has_pattern(text, _PRODUCTION_ENV_PATTERNS):
            safety_flags.append(SafetyFlag.REQUIRES_PRODUCTION_ENVIRONMENT)
            reasons.append("article appears to require a real production environment")

        if _has_pattern(text, _DESTRUCTIVE_PATTERNS):
            safety_flags.append(SafetyFlag.DESTRUCTIVE_OPERATION)
            reasons.append("article contains destructive operation patterns that cannot run in isolated lab")

        # Hard reject immediately if any hard-reject flag present
        if SafetyFlag.CONTAINS_SECRET_LIKE_CONTENT in safety_flags or \
                SafetyFlag.DANGEROUS_OR_ILLEGAL in safety_flags:
            return FeasibilityResult(
                status=FeasibilityStatus.NOT_LAB_READY,
                reasons=reasons,
                missing_requirements=missing,
                safety_flags=safety_flags,
                target_domain_candidates=domain_candidates,
                operability_score=0.0,
                verifier_feasibility=VerifierFeasibility.NOT_VERIFIABLE,
                cleanup_feasibility="blocked",
                runtime_feasibility="blocked",
                rejection_code="stub.hard_reject_safety_flag",
                evaluated_by=FeasibilityEvaluatedBy.STUB,
                evaluated_at=datetime.now(tz=timezone.utc),
            )

        # --- Domain detection ---
        k8s_hits = _count_patterns(text, _K8S_SIGNALS)
        cloud_hits = _count_patterns(text, _CLOUD_SIGNALS)

        if k8s_hits > 0:
            domain_candidates.append(TargetDomain.K8S)
        if cloud_hits > 0:
            domain_candidates.append(TargetDomain.CLOUD)
        if not domain_candidates:
            domain_candidates.append(TargetDomain.UNKNOWN)

        # Cloud domain blocked in v0.1
        if TargetDomain.CLOUD in domain_candidates and TargetDomain.K8S not in domain_candidates:
            return FeasibilityResult(
                status=FeasibilityStatus.NOT_LAB_READY,
                reasons=["cloud domain is blocked in v0.1 — only k8s domain is supported"],
                missing_requirements=[],
                safety_flags=safety_flags,
                target_domain_candidates=domain_candidates,
                operability_score=0.1,
                verifier_feasibility=VerifierFeasibility.NOT_VERIFIABLE,
                cleanup_feasibility="blocked",
                runtime_feasibility="blocked",
                rejection_code="stub.cloud_domain_blocked_v1",
                evaluated_by=FeasibilityEvaluatedBy.STUB,
                evaluated_at=datetime.now(tz=timezone.utc),
            )

        # Unknown domain → partially lab ready at best
        if TargetDomain.UNKNOWN in domain_candidates and TargetDomain.K8S not in domain_candidates:
            return FeasibilityResult(
                status=FeasibilityStatus.PARTIALLY_LAB_READY,
                reasons=["unable to determine target domain from article content"],
                missing_requirements=["clear domain indicators (k8s, linux, docker, etc.)"],
                safety_flags=safety_flags,
                target_domain_candidates=domain_candidates,
                operability_score=0.2,
                verifier_feasibility=VerifierFeasibility.NOT_VERIFIABLE,
                cleanup_feasibility="unknown",
                runtime_feasibility="unknown",
                evaluated_by=FeasibilityEvaluatedBy.STUB,
                evaluated_at=datetime.now(tz=timezone.utc),
            )

        # --- Operability check ---
        operable_count = _count_patterns(text, _OPERABLE_SIGNALS)
        non_operable_count = _count_patterns(text, _NON_OPERABLE_SIGNALS)
        has_commands = bool(re.search(r"```[\w]*\n[\s\S]+?```", text) or
                            re.search(r"(?m)^\$\s+\S", text))

        if non_operable_count > 0 and operable_count == 0:
            return FeasibilityResult(
                status=FeasibilityStatus.NOT_LAB_READY,
                reasons=["article does not appear to contain operable steps or commands"],
                missing_requirements=["executable commands or steps", "verifiable outcomes"],
                safety_flags=safety_flags,
                target_domain_candidates=domain_candidates,
                operability_score=0.05,
                verifier_feasibility=VerifierFeasibility.NOT_VERIFIABLE,
                cleanup_feasibility="unknown",
                runtime_feasibility="unknown",
                rejection_code="stub.no_operable_content",
                evaluated_by=FeasibilityEvaluatedBy.STUB,
                evaluated_at=datetime.now(tz=timezone.utc),
            )

        # --- K8s verifiability check ---
        verifier_feasibility = VerifierFeasibility.NOT_VERIFIABLE
        if TargetDomain.K8S in domain_candidates:
            verifiable = _has_pattern(text, _VERIFIABLE_K8S_SIGNALS)
            if verifiable:
                verifier_feasibility = VerifierFeasibility.NEEDS_PARAMETERIZATION

        # --- Classify into DIRECTLY_LAB_READY vs PARTIALLY_LAB_READY ---
        if (
            TargetDomain.K8S in domain_candidates
            and has_commands
            and operable_count >= 2
            and verifier_feasibility != VerifierFeasibility.NOT_VERIFIABLE
            and SafetyFlag.REQUIRES_REAL_CREDENTIALS not in safety_flags
            and SafetyFlag.REQUIRES_PRODUCTION_ENVIRONMENT not in safety_flags
            and SafetyFlag.DESTRUCTIVE_OPERATION not in safety_flags
        ):
            return FeasibilityResult(
                status=FeasibilityStatus.DIRECTLY_LAB_READY,
                reasons=["article contains k8s commands, structured steps, and verifiable outcomes"],
                missing_requirements=[],
                safety_flags=safety_flags,
                target_domain_candidates=domain_candidates,
                operability_score=0.75,
                verifier_feasibility=verifier_feasibility,
                cleanup_feasibility="namespace_delete",
                runtime_feasibility="k8s_namespace",
                evaluated_by=FeasibilityEvaluatedBy.STUB,
                evaluated_at=datetime.now(tz=timezone.utc),
            )

        # Default: PARTIALLY_LAB_READY
        if not has_commands:
            missing.append("executable commands in code blocks")
        if operable_count < 2:
            missing.append("structured steps or clear operation sequence")
        if verifier_feasibility == VerifierFeasibility.NOT_VERIFIABLE:
            missing.append("verifiable outcomes (e.g. kubectl get / describe results)")
        if SafetyFlag.REQUIRES_REAL_CREDENTIALS in safety_flags:
            missing.append("substitutable credentials (no real credentials allowed)")
        if SafetyFlag.REQUIRES_PRODUCTION_ENVIRONMENT in safety_flags:
            missing.append("isolated environment substitute for production dependency")
        if SafetyFlag.DESTRUCTIVE_OPERATION in safety_flags:
            missing.append("safe scoped operation (destructive commands cannot run in lab)")

        if not missing:
            missing.append("admin review required to confirm all experiment criteria")

        return FeasibilityResult(
            status=FeasibilityStatus.PARTIALLY_LAB_READY,
            reasons=reasons or ["article has technical content but is missing key lab criteria"],
            missing_requirements=missing,
            safety_flags=safety_flags,
            target_domain_candidates=domain_candidates,
            operability_score=0.4,
            verifier_feasibility=verifier_feasibility,
            cleanup_feasibility="unknown",
            runtime_feasibility="unknown",
            evaluated_by=FeasibilityEvaluatedBy.STUB,
            evaluated_at=datetime.now(tz=timezone.utc),
        )
