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
    ImageStatus,
    LabDraft,
    PollutionLevel,
    ValidatorResult,
    ValidatorStatus,
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
        results: list[ValidatorResult] = []

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
