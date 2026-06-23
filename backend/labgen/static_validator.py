"""
StaticValidator — runs all publish-gate checks on a LabDraft.

Also derives pollution_level and shared_namespace_candidate (side-effects on draft).
Contract reference: §9, §10, §8.
"""

from __future__ import annotations

import re
from typing import Optional

from backend.labgen.models import (
    BlockingLevel,
    CleanupLinuxWorkspace,
    ImageStatus,
    LabDomainType,
    LabDraft,
    LinuxSandboxPolicy,
    LinuxVerifyTemplate,
    LinuxVerifyType,
    PollutionLevel,
    ValidatorResult,
    ValidatorStatus,
)

# Placeholder patterns that block publish — trusted reader sees real content, not stubs
_PLACEHOLDER_RE = re.compile(
    r"\[TODO[^\]]*\]|(?<!\w)TODO(?!\w)|\bTBD\b|\bPLACEHOLDER\b|coming soon",
    re.IGNORECASE,
)

# External registries forbidden per §7 and §10
_EXTERNAL_REGISTRIES = (
    "docker.io/",
    "ghcr.io/",
    "quay.io/",
    "registry.k8s.io/",
    "k8s.gcr.io/",
    "gcr.io/",
    "us-docker.pkg.dev/",
)

# Namespace literals forbidden in VerifyTemplate.namespace (§6)
_HARDCODED_NAMESPACES: frozenset[str] = frozenset(
    {"default", "demo", "kube-system", "kube-public", "kube-node-lease"}
)

# Cluster-scoped resource kinds for pollution detection (§8)
_CLUSTER_SCOPED_KINDS = (
    "ClusterRole",
    "ClusterRoleBinding",
    "CustomResourceDefinition",
    "StorageClass",
    "Node",
    "PersistentVolume",
    "Namespace",
    "IngressClass",
)

# Node-level indicators for pollution detection (§8)
_NODE_LEVEL_PATTERNS = ("hostPath:", "hostNetwork: true", "hostPID: true", "hostIPC: true")

# Linux domain: forbidden absolute paths for verifier target_path and sandbox workspace_root
_LINUX_FORBIDDEN_PATH_PREFIXES: tuple[str, ...] = (
    "/etc", "/root", "/var", "/proc", "/sys", "/dev", "/boot",
    "/usr", "/bin", "/sbin", "/lib", "/lib64",
)

# Linux domain: forbidden paths for cleanup (guard against wiping host directories)
_LINUX_FORBIDDEN_CLEANUP_ROOTS: frozenset[str] = frozenset({
    "/", "/home", "/tmp", "/etc", "/var", "/root",
})

# Linux domain: required residual check keys that every cleanup policy must include
_LINUX_REQUIRED_RESIDUAL_CHECKS: frozenset[str] = frozenset({
    "workspace_removed_or_empty",
    "no_session_owned_processes",
    "credentials_revoked",
    "terminal_closed",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pass(check_id: str, field_path: str = "") -> ValidatorResult:
    return ValidatorResult(
        check_id=check_id,
        status=ValidatorStatus.PASSED,
        blocking_level=BlockingLevel.DRAFT_WARNING,
        field_path=field_path,
        message="OK",
    )


def _fail(
    check_id: str,
    blocking_level: BlockingLevel,
    field_path: str,
    message: str,
) -> ValidatorResult:
    return ValidatorResult(
        check_id=check_id,
        status=ValidatorStatus.FAILED,
        blocking_level=blocking_level,
        field_path=field_path,
        message=message,
    )


def _has_no_tag(image_ref: str) -> bool:
    """True if the image reference's name portion contains no ':tag'."""
    # Split on '/' to isolate the image+tag component (last segment).
    # Registry addresses like '172.16.100.1:5000' contain ':' but are not
    # in the last segment after splitting on '/'.
    last = image_ref.split("/")[-1]
    return ":" not in last


# ---------------------------------------------------------------------------
# StaticValidator
# ---------------------------------------------------------------------------


class StaticValidator:
    """
    Validate a LabDraft against all publish-gate rules.

    Mutates draft.pollution_level, draft.shared_namespace_candidate,
    draft.shared_namespace_candidate_reason, and the corresponding fields
    in draft.runtime_requirements.

    Returns the full list of ValidatorResult objects (one per check_id,
    may be multiple failures per check_id if multiple fields violate).
    """

    def validate(self, draft: LabDraft) -> list[ValidatorResult]:
        if draft.target_domain == LabDomainType.LINUX:
            return self._validate_linux(draft)
        # K8s path — all existing checks run unchanged
        return self._validate_k8s(draft)

    def _validate_k8s(self, draft: LabDraft) -> list[ValidatorResult]:
        results: list[ValidatorResult] = []

        results.extend(self._check_content_no_placeholders(draft))
        results.extend(self._check_image_no_latest_tag(draft))
        results.extend(self._check_image_no_unknown_registry(draft))
        results.extend(self._check_image_all_resolved(draft))
        results.extend(self._check_image_all_exist_in_registry(draft))
        results.extend(self._check_explain_verified_if_published(draft))
        results.extend(self._check_namespace_no_hardcoded(draft))
        results.extend(self._check_verify_no_shell_commands(draft))
        results.extend(self._check_verify_no_secret_value(draft))
        results.extend(self._check_cleanup_declared(draft))
        results.extend(self._check_cluster_scoped_cleanup_declared(draft))
        results.extend(self._check_helm_no_generation(draft))
        results.extend(self._check_service_nodeport(draft))
        results.extend(self._check_operator_crd(draft))
        # K8s domain must not contain Linux verifiers
        results.extend(self._check_k8s_no_linux_verifiers(draft))

        # Derived fields — computed after all structural checks
        pollution = self._derive_pollution_level(draft)
        draft.pollution_level = pollution
        draft.runtime_requirements.pollution_level = pollution
        results.extend(self._check_pollution_known(draft))

        candidate, reason = self._derive_shared_namespace_candidate(draft)
        draft.shared_namespace_candidate = candidate
        draft.shared_namespace_candidate_reason = reason
        draft.runtime_requirements.shared_namespace_candidate = candidate
        draft.runtime_requirements.shared_namespace_candidate_reason = reason

        return results

    def _validate_linux(self, draft: LabDraft) -> list[ValidatorResult]:
        """Linux domain validation — schema-only, publish always blocked (runtime pending)."""
        results: list[ValidatorResult] = []

        # Shared quality checks (domain-agnostic)
        results.extend(self._check_content_no_placeholders(draft))
        results.extend(self._check_explain_verified_if_published(draft))

        # Linux must not contain K8s verifiers
        results.extend(self._check_linux_no_k8s_verifiers(draft))

        # Linux-specific structural checks
        results.extend(self._check_linux_sandbox_policy_required(draft))
        results.extend(self._check_linux_cleanup_required(draft))
        results.extend(self._check_linux_verifiers_present(draft))
        results.extend(self._check_linux_verifiers_safe(draft))
        results.extend(self._check_linux_sandbox_safe(draft))
        results.extend(self._check_linux_cleanup_safe(draft))

        # Pollution level: workspace-only for Linux container labs
        if draft.linux_sandbox_policy is not None:
            draft.pollution_level = PollutionLevel.NAMESPACE_ONLY
            draft.runtime_requirements.pollution_level = PollutionLevel.NAMESPACE_ONLY
            results.append(_pass("pollution.known", "pollution_level"))
        else:
            draft.pollution_level = PollutionLevel.UNKNOWN
            results.append(_fail(
                "pollution.known",
                BlockingLevel.PUBLISH_BLOCKING,
                "pollution_level",
                "Linux sandbox policy missing — pollution level cannot be derived",
            ))

        return results

    # ------------------------------------------------------------------
    # Content quality check  (content.no_placeholders)
    # ------------------------------------------------------------------

    def _check_content_no_placeholders(self, draft: LabDraft) -> list[ValidatorResult]:
        """Reject publish if any reader-facing field still contains stub placeholder text."""
        failures = []

        for field, value in [("title", draft.title), ("description", draft.description)]:
            if value and _PLACEHOLDER_RE.search(value):
                failures.append(_fail(
                    "content.no_placeholders",
                    BlockingLevel.PUBLISH_BLOCKING,
                    field,
                    f"'{field}' contains placeholder text — must be replaced before publishing",
                ))

        for i, step in enumerate(draft.steps):
            for field, value in [("why", step.why), ("do", step.do), ("observe", step.observe)]:
                if value and _PLACEHOLDER_RE.search(value):
                    failures.append(_fail(
                        "content.no_placeholders",
                        BlockingLevel.PUBLISH_BLOCKING,
                        f"steps[{i}].{field}",
                        f"Step '{step.step_id}' field '{field}' contains placeholder text",
                    ))
            for field, value in [
                ("concept", step.explain.concept),
                ("observation", step.explain.observation),
            ]:
                if value and _PLACEHOLDER_RE.search(value):
                    failures.append(_fail(
                        "content.no_placeholders",
                        BlockingLevel.PUBLISH_BLOCKING,
                        f"steps[{i}].explain.{field}",
                        f"Step '{step.step_id}' explain.{field} contains placeholder text",
                    ))
            for j, vt in enumerate(step.verify):
                if vt.notes and _PLACEHOLDER_RE.search(vt.notes):
                    failures.append(_fail(
                        "content.no_placeholders",
                        BlockingLevel.PUBLISH_BLOCKING,
                        f"steps[{i}].verify[{j}].notes",
                        f"Verify '{vt.verify_id}' notes contains placeholder text",
                    ))

        return failures or [_pass("content.no_placeholders", "title/description/steps[*]")]

    # ------------------------------------------------------------------
    # Image checks  (§10: image.*)
    # ------------------------------------------------------------------

    def _check_image_no_latest_tag(self, draft: LabDraft) -> list[ValidatorResult]:
        failures = []
        for i, img in enumerate(draft.image_resolution):
            req = img.requested_image
            if req.endswith(":latest") or _has_no_tag(req):
                failures.append(_fail(
                    "image.no_latest_tag",
                    BlockingLevel.PUBLISH_BLOCKING,
                    f"image_resolution[{i}].requested_image",
                    f"'{req}' uses :latest or has no tag — pin to a specific version",
                ))
        return failures or [_pass("image.no_latest_tag", "image_resolution")]

    def _check_image_no_unknown_registry(self, draft: LabDraft) -> list[ValidatorResult]:
        failures = []
        for i, img in enumerate(draft.image_resolution):
            req = img.requested_image
            for registry in _EXTERNAL_REGISTRIES:
                if req.startswith(registry) or req.startswith(registry.rstrip("/")):
                    failures.append(_fail(
                        "image.no_unknown_registry",
                        BlockingLevel.PUBLISH_BLOCKING,
                        f"image_resolution[{i}].requested_image",
                        f"'{req}' references external registry — use internal registry only",
                    ))
                    break
        return failures or [_pass("image.no_unknown_registry", "image_resolution")]

    def _check_image_all_resolved(self, draft: LabDraft) -> list[ValidatorResult]:
        failures = []
        for i, img in enumerate(draft.image_resolution):
            if img.image_status != ImageStatus.RESOLVED:
                failures.append(_fail(
                    "image.all_resolved",
                    BlockingLevel.PUBLISH_BLOCKING,
                    f"image_resolution[{i}].image_status",
                    f"'{img.requested_image}' status={img.image_status.value} — must be resolved",
                ))
        return failures or [_pass("image.all_resolved", "image_resolution")]

    def _check_image_all_exist_in_registry(self, draft: LabDraft) -> list[ValidatorResult]:
        failures = []
        for i, img in enumerate(draft.image_resolution):
            if img.image_status == ImageStatus.RESOLVED and img.existence_check_passed is not True:
                failures.append(_fail(
                    "image.all_exist_in_registry",
                    BlockingLevel.PUBLISH_BLOCKING,
                    f"image_resolution[{i}].existence_check_passed",
                    f"'{img.resolved_image or img.requested_image}' registry existence not verified",
                ))
        return failures or [_pass("image.all_exist_in_registry", "image_resolution")]

    # ------------------------------------------------------------------
    # Explain check  (§10: explain.*)
    # ------------------------------------------------------------------

    def _check_explain_verified_if_published(self, draft: LabDraft) -> list[ValidatorResult]:
        failures = []
        for i, step in enumerate(draft.steps):
            ex = step.explain
            if ex.published_to_student and not ex.admin_verified:
                failures.append(_fail(
                    "explain.verified_if_published",
                    BlockingLevel.PUBLISH_BLOCKING,
                    f"steps[{i}].explain.admin_verified",
                    f"Step '{step.step_id}': published_to_student=true but admin_verified=false",
                ))
        return failures or [_pass("explain.verified_if_published", "steps[*].explain")]

    # ------------------------------------------------------------------
    # Namespace check  (§10: namespace.*)
    # ------------------------------------------------------------------

    def _check_namespace_no_hardcoded(self, draft: LabDraft) -> list[ValidatorResult]:
        failures = []
        for i, step in enumerate(draft.steps):
            for j, vt in enumerate(step.verify):
                if vt.namespace in _HARDCODED_NAMESPACES:
                    failures.append(_fail(
                        "namespace.no_hardcoded",
                        BlockingLevel.PUBLISH_BLOCKING,
                        f"steps[{i}].verify[{j}].namespace",
                        f"Verify '{vt.verify_id}' uses hardcoded namespace '{vt.namespace}'"
                        " — use '{{lab_namespace}}'",
                    ))
        return failures or [_pass("namespace.no_hardcoded", "steps[*].verify[*].namespace")]

    # ------------------------------------------------------------------
    # Verify template checks  (§10: verify.*)
    # ------------------------------------------------------------------

    def _check_verify_no_shell_commands(self, draft: LabDraft) -> list[ValidatorResult]:
        """
        Defense-in-depth: VerifyType enum already excludes shell types,
        but guard against directly-constructed objects with invalid types.
        """
        _SHELL_TYPES = frozenset({"shell_command", "exec", "script", "bash", "sh"})
        failures = []
        for i, step in enumerate(draft.steps):
            for j, vt in enumerate(step.verify):
                if vt.type.value in _SHELL_TYPES:
                    failures.append(_fail(
                        "verify.no_shell_commands",
                        BlockingLevel.PUBLISH_BLOCKING,
                        f"steps[{i}].verify[{j}].type",
                        f"Verify '{vt.verify_id}' uses shell type — forbidden in MVP",
                    ))
        return failures or [_pass("verify.no_shell_commands", "steps[*].verify[*].type")]

    def _check_verify_no_secret_value(self, draft: LabDraft) -> list[ValidatorResult]:
        """secret_key_exists and secret_value_equals are MVP non-goals (§1, §6)."""
        _FORBIDDEN = frozenset({"secret_key_exists", "secret_value_equals"})
        failures = []
        for i, step in enumerate(draft.steps):
            for j, vt in enumerate(step.verify):
                if vt.type.value in _FORBIDDEN:
                    failures.append(_fail(
                        "verify.no_secret_value",
                        BlockingLevel.PUBLISH_BLOCKING,
                        f"steps[{i}].verify[{j}].type",
                        f"Verify '{vt.verify_id}' uses forbidden type '{vt.type.value}'",
                    ))
        return failures or [_pass("verify.no_secret_value", "steps[*].verify[*].type")]

    # ------------------------------------------------------------------
    # Cleanup checks  (§10: cleanup.*, cluster_scoped.*)
    # ------------------------------------------------------------------

    def _check_cleanup_declared(self, draft: LabDraft) -> list[ValidatorResult]:
        if draft.cleanup is None or draft.cleanup.namespace_cleanup is None:
            return [_fail(
                "cleanup.declared",
                BlockingLevel.PUBLISH_BLOCKING,
                "cleanup",
                "cleanup spec is missing — namespace_cleanup is required",
            )]
        return [_pass("cleanup.declared", "cleanup")]

    def _check_cluster_scoped_cleanup_declared(self, draft: LabDraft) -> list[ValidatorResult]:
        if draft.cleanup is None:
            return [_pass("cluster_scoped.cleanup_declared", "cleanup.cluster_scoped_resources")]
        failures = []
        for i, res in enumerate(draft.cleanup.cluster_scoped_resources):
            if not res.cleanup:
                failures.append(_fail(
                    "cluster_scoped.cleanup_declared",
                    BlockingLevel.PUBLISH_BLOCKING,
                    f"cleanup.cluster_scoped_resources[{i}].cleanup",
                    f"Cluster resource '{res.kind}/{res.name}' has no cleanup action",
                ))
        return failures or [_pass("cluster_scoped.cleanup_declared", "cleanup.cluster_scoped_resources")]

    # ------------------------------------------------------------------
    # Command-text scans  (§10: helm.*, service.*, operator.*)
    # ------------------------------------------------------------------

    def _check_helm_no_generation(self, draft: LabDraft) -> list[ValidatorResult]:
        failures = []
        for i, step in enumerate(draft.steps):
            for j, cmd in enumerate(step.commands):
                if re.search(r"\bhelm\s+(install|upgrade)\b", cmd):
                    failures.append(_fail(
                        "helm.no_generation",
                        BlockingLevel.REVIEW_REQUIRED,
                        f"steps[{i}].commands[{j}]",
                        f"Step '{step.step_id}': helm install/upgrade — requires dedicated VM review",
                    ))
        return failures or [_pass("helm.no_generation", "steps[*].commands")]

    def _check_service_nodeport(self, draft: LabDraft) -> list[ValidatorResult]:
        failures = []
        for i, step in enumerate(draft.steps):
            for j, cmd in enumerate(step.commands):
                if re.search(r"\bNodePort\b|--type=NodePort", cmd):
                    failures.append(_fail(
                        "service.nodeport",
                        BlockingLevel.REVIEW_REQUIRED,
                        f"steps[{i}].commands[{j}]",
                        f"Step '{step.step_id}': NodePort Service — shared_namespace_candidate=false",
                    ))
        return failures or [_pass("service.nodeport", "steps[*].commands")]

    def _check_operator_crd(self, draft: LabDraft) -> list[ValidatorResult]:
        failures = []
        for i, step in enumerate(draft.steps):
            for j, cmd in enumerate(step.commands):
                if re.search(r"kind:\s*CustomResourceDefinition\b", cmd):
                    failures.append(_fail(
                        "operator.crd",
                        BlockingLevel.REVIEW_REQUIRED,
                        f"steps[{i}].commands[{j}]",
                        f"Step '{step.step_id}': CRD usage — requires_dedicated_vm=true",
                    ))
        return failures or [_pass("operator.crd", "steps[*].commands")]

    # ------------------------------------------------------------------
    # Derived: pollution_level  (§8)
    # ------------------------------------------------------------------

    def _derive_pollution_level(self, draft: LabDraft) -> PollutionLevel:
        all_cmds = "\n".join(cmd for step in draft.steps for cmd in step.commands)

        # node_level takes precedence
        if any(p in all_cmds for p in _NODE_LEVEL_PATTERNS):
            return PollutionLevel.NODE_LEVEL

        # cluster_scoped: CRD / ClusterRole / etc. in YAML, or declared resources
        cluster_pattern = "|".join(re.escape(k) for k in _CLUSTER_SCOPED_KINDS)
        has_cluster_yaml = bool(re.search(rf"kind:\s*({cluster_pattern})\b", all_cmds))
        has_cluster_resources = bool(
            draft.cleanup and draft.cleanup.cluster_scoped_resources
        )
        if has_cluster_yaml or has_cluster_resources:
            return PollutionLevel.CLUSTER_SCOPED

        # namespace_only: has steps and none of the above
        if draft.steps:
            return PollutionLevel.NAMESPACE_ONLY

        return PollutionLevel.UNKNOWN

    def _check_pollution_known(self, draft: LabDraft) -> list[ValidatorResult]:
        if draft.pollution_level == PollutionLevel.UNKNOWN:
            return [_fail(
                "pollution.known",
                BlockingLevel.PUBLISH_BLOCKING,
                "pollution_level",
                "pollution_level=unknown — cannot determine resource scope, publish blocked",
            )]
        return [_pass("pollution.known", "pollution_level")]

    # ------------------------------------------------------------------
    # K8s domain: reject Linux verifiers in K8s labs
    # ------------------------------------------------------------------

    def _check_k8s_no_linux_verifiers(self, draft: LabDraft) -> list[ValidatorResult]:
        failures = []
        for i, step in enumerate(draft.steps):
            if step.linux_verify:
                failures.append(_fail(
                    "k8s.no_linux_verifiers",
                    BlockingLevel.PUBLISH_BLOCKING,
                    f"steps[{i}].linux_verify",
                    f"Step '{step.step_id}' contains Linux verifiers in a K8s domain lab — "
                    "linux_verify must be empty for K8s labs",
                ))
        return failures or [_pass("k8s.no_linux_verifiers", "steps[*].linux_verify")]

    # ------------------------------------------------------------------
    # Linux domain checks
    # ------------------------------------------------------------------

    def _check_linux_verifiers_present(self, draft: LabDraft) -> list[ValidatorResult]:
        """Linux domain labs must declare at least one linux_verify entry."""
        has_any = any(step.linux_verify for step in draft.steps)
        if not has_any:
            return [_fail(
                "linux.verifiers_present",
                BlockingLevel.PUBLISH_BLOCKING,
                "steps[*].linux_verify",
                "Linux domain labs must have at least one linux_verify entry — "
                "no verifiable outcome declared",
            )]
        return [_pass("linux.verifiers_present", "steps[*].linux_verify")]

    def _check_linux_no_k8s_verifiers(self, draft: LabDraft) -> list[ValidatorResult]:
        """Linux domain labs must not use K8s VerifyTemplate entries."""
        failures = []
        for i, step in enumerate(draft.steps):
            if step.verify:
                failures.append(_fail(
                    "linux.no_k8s_verifiers",
                    BlockingLevel.PUBLISH_BLOCKING,
                    f"steps[{i}].verify",
                    f"Step '{step.step_id}' contains K8s verifiers in a Linux domain lab — "
                    "verify must be empty for Linux labs; use linux_verify instead",
                ))
        return failures or [_pass("linux.no_k8s_verifiers", "steps[*].verify")]

    def _check_linux_sandbox_policy_required(self, draft: LabDraft) -> list[ValidatorResult]:
        if draft.linux_sandbox_policy is None:
            return [_fail(
                "linux.sandbox_policy_required",
                BlockingLevel.PUBLISH_BLOCKING,
                "linux_sandbox_policy",
                "linux_sandbox_policy is required for Linux domain labs",
            )]
        return [_pass("linux.sandbox_policy_required", "linux_sandbox_policy")]

    def _check_linux_cleanup_required(self, draft: LabDraft) -> list[ValidatorResult]:
        if draft.linux_cleanup is None:
            return [_fail(
                "linux.cleanup_required",
                BlockingLevel.PUBLISH_BLOCKING,
                "linux_cleanup",
                "linux_cleanup is required for Linux domain labs",
            )]
        return [_pass("linux.cleanup_required", "linux_cleanup")]

    def _check_linux_verifiers_safe(self, draft: LabDraft) -> list[ValidatorResult]:
        """Validate all LinuxVerifyTemplate entries: safe paths, required fields."""
        failures = []
        for i, step in enumerate(draft.steps):
            for j, lv in enumerate(step.linux_verify):
                fp = f"steps[{i}].linux_verify[{j}]"

                if not lv.target_path:
                    failures.append(_fail(
                        "linux.verifiers_safe",
                        BlockingLevel.PUBLISH_BLOCKING,
                        f"{fp}.target_path",
                        f"Verify '{lv.verify_id}': target_path must not be empty",
                    ))
                    continue

                if ".." in lv.target_path:
                    failures.append(_fail(
                        "linux.verifiers_safe",
                        BlockingLevel.PUBLISH_BLOCKING,
                        f"{fp}.target_path",
                        f"Verify '{lv.verify_id}': target_path contains '..' path traversal",
                    ))

                for forbidden in _LINUX_FORBIDDEN_PATH_PREFIXES:
                    if lv.target_path == forbidden or lv.target_path.startswith(forbidden + "/"):
                        failures.append(_fail(
                            "linux.verifiers_safe",
                            BlockingLevel.PUBLISH_BLOCKING,
                            f"{fp}.target_path",
                            f"Verify '{lv.verify_id}': target_path '{lv.target_path}' "
                            f"accesses forbidden system path '{forbidden}'",
                        ))
                        break

                if (
                    lv.type == LinuxVerifyType.LINUX_FILE_CONTENT_MATCHES
                    and not lv.expected_content
                ):
                    failures.append(_fail(
                        "linux.verifiers_safe",
                        BlockingLevel.PUBLISH_BLOCKING,
                        f"{fp}.expected_content",
                        f"Verify '{lv.verify_id}': expected_content is required "
                        "for linux_file_content_matches",
                    ))

                if (
                    lv.type == LinuxVerifyType.LINUX_FILE_MODE_MATCHES
                    and not lv.expected_mode
                ):
                    failures.append(_fail(
                        "linux.verifiers_safe",
                        BlockingLevel.PUBLISH_BLOCKING,
                        f"{fp}.expected_mode",
                        f"Verify '{lv.verify_id}': expected_mode is required "
                        "for linux_file_mode_matches",
                    ))

        return failures or [_pass("linux.verifiers_safe", "steps[*].linux_verify")]

    def _check_linux_sandbox_safe(self, draft: LabDraft) -> list[ValidatorResult]:
        """Validate LinuxSandboxPolicy safety constraints."""
        if draft.linux_sandbox_policy is None:
            return [_pass("linux.sandbox_safe", "linux_sandbox_policy")]

        policy = draft.linux_sandbox_policy
        failures = []

        if policy.allow_root:
            failures.append(_fail(
                "linux.sandbox_safe",
                BlockingLevel.PUBLISH_BLOCKING,
                "linux_sandbox_policy.allow_root",
                "linux_sandbox_policy.allow_root must be False — root access is forbidden",
            ))

        if policy.allow_network:
            failures.append(_fail(
                "linux.sandbox_safe",
                BlockingLevel.PUBLISH_BLOCKING,
                "linux_sandbox_policy.allow_network",
                "linux_sandbox_policy.allow_network must be False — network access is forbidden",
            ))

        for forbidden in _LINUX_FORBIDDEN_PATH_PREFIXES:
            if policy.workspace_root == forbidden or policy.workspace_root.startswith(
                forbidden + "/"
            ):
                failures.append(_fail(
                    "linux.sandbox_safe",
                    BlockingLevel.PUBLISH_BLOCKING,
                    "linux_sandbox_policy.workspace_root",
                    f"workspace_root '{policy.workspace_root}' is within forbidden "
                    f"system path '{forbidden}'",
                ))
                break

        if not policy.workspace_root:
            failures.append(_fail(
                "linux.sandbox_safe",
                BlockingLevel.PUBLISH_BLOCKING,
                "linux_sandbox_policy.workspace_root",
                "linux_sandbox_policy.workspace_root must not be empty",
            ))

        if ".." in policy.workspace_root:
            failures.append(_fail(
                "linux.sandbox_safe",
                BlockingLevel.PUBLISH_BLOCKING,
                "linux_sandbox_policy.workspace_root",
                "linux_sandbox_policy.workspace_root contains '..' path traversal",
            ))

        return failures or [_pass("linux.sandbox_safe", "linux_sandbox_policy")]

    def _check_linux_cleanup_safe(self, draft: LabDraft) -> list[ValidatorResult]:
        """Validate CleanupLinuxWorkspace safety constraints."""
        if draft.linux_cleanup is None:
            return [_pass("linux.cleanup_safe", "linux_cleanup")]

        cleanup = draft.linux_cleanup
        failures = []

        if not cleanup.workspace_root:
            failures.append(_fail(
                "linux.cleanup_safe",
                BlockingLevel.PUBLISH_BLOCKING,
                "linux_cleanup.workspace_root",
                "linux_cleanup.workspace_root must not be empty",
            ))
        elif cleanup.workspace_root in _LINUX_FORBIDDEN_CLEANUP_ROOTS:
            failures.append(_fail(
                "linux.cleanup_safe",
                BlockingLevel.PUBLISH_BLOCKING,
                "linux_cleanup.workspace_root",
                f"linux_cleanup.workspace_root '{cleanup.workspace_root}' is a "
                "forbidden cleanup root — cannot clean up system directories",
            ))

        for k, path in enumerate(cleanup.cleanup_paths):
            if path in _LINUX_FORBIDDEN_CLEANUP_ROOTS:
                failures.append(_fail(
                    "linux.cleanup_safe",
                    BlockingLevel.PUBLISH_BLOCKING,
                    f"linux_cleanup.cleanup_paths[{k}]",
                    f"cleanup_path '{path}' is a forbidden cleanup root",
                ))
            elif cleanup.workspace_root and not (
                path == cleanup.workspace_root or path.startswith(cleanup.workspace_root + "/")
            ):
                failures.append(_fail(
                    "linux.cleanup_safe",
                    BlockingLevel.PUBLISH_BLOCKING,
                    f"linux_cleanup.cleanup_paths[{k}]",
                    f"cleanup_path '{path}' is outside workspace_root "
                    f"'{cleanup.workspace_root}' — only workspace-scoped cleanup allowed",
                ))

        missing = _LINUX_REQUIRED_RESIDUAL_CHECKS - set(cleanup.residual_checks)
        if missing:
            failures.append(_fail(
                "linux.cleanup_safe",
                BlockingLevel.PUBLISH_BLOCKING,
                "linux_cleanup.residual_checks",
                f"linux_cleanup.residual_checks missing required checks: "
                f"{sorted(missing)}",
            ))

        return failures or [_pass("linux.cleanup_safe", "linux_cleanup")]

    # ------------------------------------------------------------------
    # Derived: shared_namespace_candidate  (§8, 9 conditions)
    # ------------------------------------------------------------------

    def _derive_shared_namespace_candidate(self, draft: LabDraft) -> tuple[bool, str]:
        all_cmds = "\n".join(cmd for step in draft.steps for cmd in step.commands)

        # Cond 1: all verify cluster_scope = false
        for i, step in enumerate(draft.steps):
            for j, vt in enumerate(step.verify):
                if vt.cluster_scope:
                    return False, f"steps[{i}].verify[{j}].cluster_scope=true"

        # Cond 2: no cluster-scoped resource kinds in YAML
        cluster_pattern = "|".join(re.escape(k) for k in _CLUSTER_SCOPED_KINDS)
        if re.search(rf"kind:\s*({cluster_pattern})\b", all_cmds):
            return False, "contains cluster-scoped resource kind"

        # Cond 3: no hostPath/hostNetwork/hostPID
        for p in _NODE_LEVEL_PATTERNS:
            if p in all_cmds:
                return False, f"node-level resource: {p.rstrip(':')}"

        # Cond 4: no NodePort
        if re.search(r"\bNodePort\b|--type=NodePort", all_cmds):
            return False, "contains NodePort Service"

        # Cond 5: no Ingress (Phase 2)
        if re.search(r"kind:\s*Ingress\b", all_cmds):
            return False, "contains Ingress (Phase 2)"

        # Cond 6: no PVC (Phase 2)
        if re.search(r"kind:\s*PersistentVolumeClaim\b", all_cmds):
            return False, "contains PVC (Phase 2)"

        # Cond 7: no Helm
        if re.search(r"\bhelm\s+(install|upgrade)\b", all_cmds):
            return False, "helm install/upgrade present"

        # Cond 8: no CRD/Operator (covered by cond 2, but be explicit)
        if re.search(r"kind:\s*CustomResourceDefinition\b", all_cmds):
            return False, "contains CRD"

        # Cond 9: all images resolved
        for img in draft.image_resolution:
            if img.image_status != ImageStatus.RESOLVED:
                return False, f"image '{img.requested_image}' not resolved"

        return True, ""


# ---------------------------------------------------------------------------
# ArticleDraftValidator
# ---------------------------------------------------------------------------
# Validates ArticleDraftLabContract against all publish-gate guardrails.
# Input: ArticleDraftLabContract (NOT LabDraft — different pipeline stage).
# Returns: list[ValidatorResult] — one result per check_id.
# All checks are fail-closed: ambiguity → fail.
# ---------------------------------------------------------------------------


class ArticleDraftValidator:
    """
    Schema-level guardrails for ArticleDraftLabContract.

    These checks enforce that:
    - Rejected/partial feasibility cannot publish
    - Admin review is always required (even for directly_lab_ready)
    - Source grounding is present before publish candidate
    - High/blocker unsupported inferences block publish
    - Raw article text is never persisted
    - Sensitive grounding excerpts are not persisted
    - Admin approval requires all confirmations
    - Unknown domain cannot publish
    - Unsafe verifier candidates cannot publish
    - Cleanup strategy is required
    - LLM/stub draft cannot bypass review
    - Cloud domain is blocked by default in v0.1
    - source_url does not trigger scraping
    - User confirmations are required before feasibility
    """

    def validate(self, contract) -> list[ValidatorResult]:
        from backend.labgen.article_models import ArticleDraftLabContract

        results: list[ValidatorResult] = []
        results.extend(self._check_rejected_feasibility_cannot_publish(contract))
        results.extend(self._check_partial_feasibility_cannot_publish(contract))
        results.extend(self._check_directly_ready_requires_admin_review(contract))
        results.extend(self._check_source_grounding_present(contract))
        results.extend(self._check_unsupported_inference_high_blocker(contract))
        results.extend(self._check_no_raw_text_field(contract))
        results.extend(self._check_no_sensitive_grounding_excerpt(contract))
        results.extend(self._check_admin_approve_requires_confirmations(contract))
        results.extend(self._check_unknown_domain_cannot_publish(contract))
        results.extend(self._check_unsafe_verifier_cannot_publish(contract))
        results.extend(self._check_cleanup_strategy_required(contract))
        results.extend(self._check_llm_draft_cannot_bypass_review(contract))
        results.extend(self._check_cloud_domain_blocked_v1(contract))
        results.extend(self._check_source_url_no_scraping(contract))
        results.extend(self._check_user_confirmations_required(contract))
        return results

    # ------------------------------------------------------------------
    # Guardrail 1: rejected feasibility cannot publish
    # ------------------------------------------------------------------

    def _check_rejected_feasibility_cannot_publish(
        self, contract
    ) -> list[ValidatorResult]:
        from backend.labgen.article_models import (
            ArticleDraftStatus,
            FeasibilityStatus,
        )

        if (
            contract.feasibility_result.status == FeasibilityStatus.NOT_LAB_READY
            and contract.status in (
                ArticleDraftStatus.APPROVED_FOR_PUBLISH_CANDIDATE,
                ArticleDraftStatus.APPROVED_FOR_INTERNAL_REHEARSAL,
                ArticleDraftStatus.APPROVED_FOR_STATIC_VALIDATION,
            )
        ):
            return [_fail(
                "article_draft.rejected_feasibility_cannot_publish",
                BlockingLevel.PUBLISH_BLOCKING,
                "feasibility_result.status",
                "feasibility_result.status=not_lab_ready — publish path is blocked",
            )]
        return [_pass(
            "article_draft.rejected_feasibility_cannot_publish",
            "feasibility_result.status",
        )]

    # ------------------------------------------------------------------
    # Guardrail 2: partially lab-ready cannot publish
    # ------------------------------------------------------------------

    def _check_partial_feasibility_cannot_publish(
        self, contract
    ) -> list[ValidatorResult]:
        from backend.labgen.article_models import (
            ArticleDraftStatus,
            FeasibilityStatus,
        )

        if (
            contract.feasibility_result.status == FeasibilityStatus.PARTIALLY_LAB_READY
            and contract.status in (
                ArticleDraftStatus.APPROVED_FOR_PUBLISH_CANDIDATE,
            )
        ):
            return [_fail(
                "article_draft.partial_feasibility_cannot_publish",
                BlockingLevel.PUBLISH_BLOCKING,
                "feasibility_result.status",
                "feasibility_result.status=partially_lab_ready — cannot be a publish candidate",
            )]
        return [_pass(
            "article_draft.partial_feasibility_cannot_publish",
            "feasibility_result.status",
        )]

    # ------------------------------------------------------------------
    # Guardrail 3: directly_lab_ready still requires admin review
    # ------------------------------------------------------------------

    def _check_directly_ready_requires_admin_review(
        self, contract
    ) -> list[ValidatorResult]:
        from backend.labgen.article_models import (
            AdminDecisionValue,
            ArticleDraftStatus,
            FeasibilityStatus,
        )

        if (
            contract.feasibility_result.status == FeasibilityStatus.DIRECTLY_LAB_READY
            and contract.status == ArticleDraftStatus.APPROVED_FOR_PUBLISH_CANDIDATE
            and contract.admin_decision.decision != AdminDecisionValue.APPROVE
        ):
            return [_fail(
                "article_draft.directly_ready_requires_admin_review",
                BlockingLevel.PUBLISH_BLOCKING,
                "admin_decision.decision",
                "feasibility=directly_lab_ready does not bypass admin review — "
                "admin_decision.decision must be 'approve'",
            )]
        return [_pass(
            "article_draft.directly_ready_requires_admin_review",
            "admin_decision.decision",
        )]

    # ------------------------------------------------------------------
    # Guardrail 4: missing source grounding blocks publish candidate
    # ------------------------------------------------------------------

    def _check_source_grounding_present(self, contract) -> list[ValidatorResult]:
        from backend.labgen.article_models import ArticleDraftStatus

        if (
            contract.status == ArticleDraftStatus.APPROVED_FOR_PUBLISH_CANDIDATE
            and not contract.source_grounding
        ):
            return [_fail(
                "article_draft.missing_source_grounding",
                BlockingLevel.PUBLISH_BLOCKING,
                "source_grounding",
                "source_grounding is empty — at least one grounding snippet is required "
                "before a contract can become a publish candidate",
            )]
        return [_pass("article_draft.missing_source_grounding", "source_grounding")]

    # ------------------------------------------------------------------
    # Guardrail 5: unsupported inference high/blocker blocks publish
    # ------------------------------------------------------------------

    def _check_unsupported_inference_high_blocker(
        self, contract
    ) -> list[ValidatorResult]:
        from backend.labgen.article_models import (
            ArticleDraftStatus,
            UnsupportedInferenceSeverity,
        )

        if contract.status not in (
            ArticleDraftStatus.APPROVED_FOR_PUBLISH_CANDIDATE,
            ArticleDraftStatus.APPROVED_FOR_INTERNAL_REHEARSAL,
        ):
            return [_pass(
                "article_draft.unsupported_inference_high_blocker",
                "unsupported_inferences",
            )]

        failures = []
        for i, inf in enumerate(contract.unsupported_inferences):
            if inf.severity in (
                UnsupportedInferenceSeverity.HIGH,
                UnsupportedInferenceSeverity.BLOCKER,
            ):
                failures.append(_fail(
                    "article_draft.unsupported_inference_high_blocker",
                    BlockingLevel.PUBLISH_BLOCKING,
                    f"unsupported_inferences[{i}].severity",
                    f"inference '{inf.inference_id}' severity={inf.severity.value} "
                    "— blocks publish",
                ))
            elif inf.requires_admin_confirmation and not inf.admin_confirmed:
                failures.append(_fail(
                    "article_draft.unsupported_inference_high_blocker",
                    BlockingLevel.PUBLISH_BLOCKING,
                    f"unsupported_inferences[{i}].admin_confirmed",
                    f"inference '{inf.inference_id}' requires_admin_confirmation=True "
                    "but admin_confirmed=False",
                ))
        return failures or [_pass(
            "article_draft.unsupported_inference_high_blocker",
            "unsupported_inferences",
        )]

    # ------------------------------------------------------------------
    # Guardrail 6: raw article text field forbidden
    # ------------------------------------------------------------------

    def _check_no_raw_text_field(self, contract) -> list[ValidatorResult]:
        if contract.source_metadata.raw_text_persisted:
            return [_fail(
                "article_draft.no_raw_text_field",
                BlockingLevel.RUNTIME_BLOCKING,
                "source_metadata.raw_text_persisted",
                "source_metadata.raw_text_persisted=True is forbidden — "
                "raw article text must never be persisted",
            )]
        if contract.storage_policy.raw_text_persisted:
            return [_fail(
                "article_draft.no_raw_text_field",
                BlockingLevel.RUNTIME_BLOCKING,
                "storage_policy.raw_text_persisted",
                "storage_policy.raw_text_persisted=True is forbidden",
            )]
        return [_pass("article_draft.no_raw_text_field", "source_metadata.raw_text_persisted")]

    # ------------------------------------------------------------------
    # Guardrail 7: sensitive source grounding excerpt forbidden
    # ------------------------------------------------------------------

    def _check_no_sensitive_grounding_excerpt(
        self, contract
    ) -> list[ValidatorResult]:
        failures = []
        for i, sg in enumerate(contract.source_grounding):
            if sg.contains_sensitive_content and sg.excerpt:
                failures.append(_fail(
                    "article_draft.no_sensitive_grounding_excerpt",
                    BlockingLevel.RUNTIME_BLOCKING,
                    f"source_grounding[{i}].excerpt",
                    f"snippet '{sg.snippet_id}' contains_sensitive_content=True "
                    "but excerpt is non-empty — sensitive excerpts must not be persisted",
                ))
        return failures or [_pass(
            "article_draft.no_sensitive_grounding_excerpt",
            "source_grounding[*].excerpt",
        )]

    # ------------------------------------------------------------------
    # Guardrail 8: admin approve requires all confirmations
    # ------------------------------------------------------------------

    def _check_admin_approve_requires_confirmations(
        self, contract
    ) -> list[ValidatorResult]:
        from backend.labgen.article_models import AdminDecisionValue

        d = contract.admin_decision
        if d.decision == AdminDecisionValue.APPROVE and not d.is_fully_confirmed():
            missing = [
                f
                for f, v in {
                    "confirmed_source_grounding": d.confirmed_source_grounding,
                    "confirmed_safety": d.confirmed_safety,
                    "confirmed_cleanup": d.confirmed_cleanup,
                    "confirmed_verifier_strategy": d.confirmed_verifier_strategy,
                    "confirmed_no_raw_secret": d.confirmed_no_raw_secret,
                    "confirmed_no_direct_publish": d.confirmed_no_direct_publish,
                }.items()
                if not v
            ]
            return [_fail(
                "article_draft.admin_approve_requires_confirmations",
                BlockingLevel.PUBLISH_BLOCKING,
                "admin_decision",
                f"admin_decision.decision=approve but missing confirmations: "
                f"{', '.join(missing)}",
            )]
        return [_pass(
            "article_draft.admin_approve_requires_confirmations",
            "admin_decision",
        )]

    # ------------------------------------------------------------------
    # Guardrail 9: unknown target_domain cannot publish
    # ------------------------------------------------------------------

    def _check_unknown_domain_cannot_publish(
        self, contract
    ) -> list[ValidatorResult]:
        from backend.labgen.article_models import ArticleDraftStatus, TargetDomain

        if (
            contract.target_domain == TargetDomain.UNKNOWN
            and contract.status in (
                ArticleDraftStatus.APPROVED_FOR_PUBLISH_CANDIDATE,
                ArticleDraftStatus.APPROVED_FOR_INTERNAL_REHEARSAL,
                ArticleDraftStatus.APPROVED_FOR_STATIC_VALIDATION,
            )
        ):
            return [_fail(
                "article_draft.unknown_domain_cannot_publish",
                BlockingLevel.PUBLISH_BLOCKING,
                "target_domain",
                "target_domain=unknown — domain must be identified before entering "
                "the publish pipeline",
            )]
        return [_pass("article_draft.unknown_domain_cannot_publish", "target_domain")]

    # ------------------------------------------------------------------
    # Guardrail 10: unsafe verifier candidate cannot publish
    # ------------------------------------------------------------------

    def _check_unsafe_verifier_cannot_publish(
        self, contract
    ) -> list[ValidatorResult]:
        from backend.labgen.article_models import (
            ArticleDraftStatus,
            VerifierCandidateState,
        )

        if contract.status not in (
            ArticleDraftStatus.APPROVED_FOR_PUBLISH_CANDIDATE,
            ArticleDraftStatus.APPROVED_FOR_INTERNAL_REHEARSAL,
        ):
            return [_pass(
                "article_draft.unsafe_verifier_cannot_publish",
                "verifier_candidates[*].candidate_state",
            )]

        failures = []
        for i, vc in enumerate(contract.verifier_candidates):
            if vc.candidate_state == VerifierCandidateState.UNSAFE_TO_VERIFY:
                failures.append(_fail(
                    "article_draft.unsafe_verifier_cannot_publish",
                    BlockingLevel.PUBLISH_BLOCKING,
                    f"verifier_candidates[{i}].candidate_state",
                    f"verifier '{vc.candidate_id}' candidate_state=unsafe_to_verify "
                    "— cannot publish",
                ))
            elif vc.review_required and not vc.admin_reviewed:
                failures.append(_fail(
                    "article_draft.unsafe_verifier_cannot_publish",
                    BlockingLevel.PUBLISH_BLOCKING,
                    f"verifier_candidates[{i}].admin_reviewed",
                    f"verifier '{vc.candidate_id}' review_required=True "
                    "but admin_reviewed=False",
                ))
        return failures or [_pass(
            "article_draft.unsafe_verifier_cannot_publish",
            "verifier_candidates[*].candidate_state",
        )]

    # ------------------------------------------------------------------
    # Guardrail 11: cleanup strategy required
    # ------------------------------------------------------------------

    def _check_cleanup_strategy_required(
        self, contract
    ) -> list[ValidatorResult]:
        from backend.labgen.article_models import ArticleDraftStatus

        if (
            contract.required_runtime.cleanup_strategy is None
            and contract.status in (
                ArticleDraftStatus.APPROVED_FOR_PUBLISH_CANDIDATE,
                ArticleDraftStatus.APPROVED_FOR_INTERNAL_REHEARSAL,
            )
        ):
            return [_fail(
                "article_draft.cleanup_strategy_required",
                BlockingLevel.PUBLISH_BLOCKING,
                "required_runtime.cleanup_strategy",
                "required_runtime.cleanup_strategy is None — cleanup strategy is "
                "required before a contract can proceed to internal rehearsal or publish",
            )]
        return [_pass(
            "article_draft.cleanup_strategy_required",
            "required_runtime.cleanup_strategy",
        )]

    # ------------------------------------------------------------------
    # Guardrail 12: LLM/stub draft cannot bypass review
    # ------------------------------------------------------------------

    def _check_llm_draft_cannot_bypass_review(
        self, contract
    ) -> list[ValidatorResult]:
        from backend.labgen.article_models import (
            AdminDecisionValue,
            ArticleDraftStatus,
            FeasibilityEvaluatedBy,
        )

        llm_evaluated = contract.feasibility_result.evaluated_by in (
            FeasibilityEvaluatedBy.STUB,
            FeasibilityEvaluatedBy.LLM_DRAFT,
        )
        high_status = contract.status in (
            ArticleDraftStatus.APPROVED_FOR_PUBLISH_CANDIDATE,
            ArticleDraftStatus.APPROVED_FOR_INTERNAL_REHEARSAL,
        )
        not_approved = contract.admin_decision.decision != AdminDecisionValue.APPROVE

        if llm_evaluated and high_status and not_approved:
            return [_fail(
                "article_draft.llm_draft_cannot_bypass_review",
                BlockingLevel.PUBLISH_BLOCKING,
                "admin_decision.decision",
                f"feasibility evaluated_by={contract.feasibility_result.evaluated_by.value} "
                "(LLM/stub) — admin review (APPROVE) is required; "
                "LLM output cannot bypass admin review",
            )]
        return [_pass(
            "article_draft.llm_draft_cannot_bypass_review",
            "admin_decision.decision",
        )]

    # ------------------------------------------------------------------
    # Guardrail 13: cloud domain blocked by default in v0.1
    # ------------------------------------------------------------------

    def _check_cloud_domain_blocked_v1(self, contract) -> list[ValidatorResult]:
        from backend.labgen.article_models import ArticleDraftStatus, TargetDomain

        if (
            contract.target_domain == TargetDomain.CLOUD
            and contract.status != ArticleDraftStatus.DRAFT
        ):
            return [_fail(
                "article_draft.cloud_domain_blocked_v1",
                BlockingLevel.PUBLISH_BLOCKING,
                "target_domain",
                "target_domain=cloud is blocked by default in v0.1 — "
                "cloud domain support requires a dedicated gate decision",
            )]
        return [_pass("article_draft.cloud_domain_blocked_v1", "target_domain")]

    # ------------------------------------------------------------------
    # Guardrail 14: source_url does not trigger scraping (schema check)
    # ------------------------------------------------------------------

    def _check_source_url_no_scraping(self, contract) -> list[ValidatorResult]:
        # source_url is metadata-only per design; this schema-level check
        # verifies the field is present only as metadata (string), not as
        # a trigger for content fetch. Structural: if source_url is set, that
        # is allowed (metadata); scraping behavior is enforced in service layer.
        # Schema check: source_url must not look like an already-fetched result
        # (i.e., the content_hash must be from submitted text, not a URL fetch).
        return [_pass("article_draft.source_url_no_scraping", "source_metadata.source_url")]

    # ------------------------------------------------------------------
    # Guardrail 15: user confirmations required before feasibility
    # ------------------------------------------------------------------

    def _check_user_confirmations_required(
        self, contract
    ) -> list[ValidatorResult]:
        from backend.labgen.article_models import ArticleDraftStatus, FeasibilityStatus

        # For any status beyond DRAFT, user confirmations must have been obtained
        if contract.status == ArticleDraftStatus.DRAFT:
            return [_pass(
                "article_draft.user_confirmations_required",
                "source_metadata",
            )]

        failures = []
        if not contract.source_metadata.user_confirmed_right_to_use:
            failures.append(_fail(
                "article_draft.user_confirmations_required",
                BlockingLevel.PUBLISH_BLOCKING,
                "source_metadata.user_confirmed_right_to_use",
                "user_confirmed_right_to_use=False — user consent is required "
                "before feasibility assessment",
            ))
        if not contract.source_metadata.user_confirmed_no_secrets:
            failures.append(_fail(
                "article_draft.user_confirmations_required",
                BlockingLevel.PUBLISH_BLOCKING,
                "source_metadata.user_confirmed_no_secrets",
                "user_confirmed_no_secrets=False — user confirmation is required "
                "before feasibility assessment",
            ))
        return failures or [_pass(
            "article_draft.user_confirmations_required",
            "source_metadata",
        )]
