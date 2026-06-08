"""Tests for backend/labgen/static_validator.py — all check_ids pass/fail."""

import pytest

pytestmark = pytest.mark.static

from backend.labgen.models import (
    BlockingLevel,
    CleanupNamespace,
    CleanupSpec,
    ClusterScopedResource,
    ExplainField,
    ImageResolutionResult,
    ImageStatus,
    LabDraft,
    PollutionLevel,
    RuntimeRequirements,
    Step,
    ValidatorStatus,
    VerifyTemplate,
    VerifyType,
)
from backend.labgen.static_validator import StaticValidator


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _explain(**kw) -> ExplainField:
    defaults = dict(concept="concept", observation="observation")
    defaults.update(kw)
    return ExplainField(**defaults)


def _step(step_id="s1", commands=None, verify=None, explain=None, **kw) -> Step:
    return Step(
        step_id=step_id,
        order=1,
        why="why",
        do="do",
        observe="observe",
        commands=commands or [],
        verify=verify or [],
        explain=explain or _explain(),
        **kw,
    )


def _vt(verify_id="v1", type=VerifyType.POD_RUNNING, name="nginx",
        namespace="{{lab_namespace}}", cluster_scope=False, **kw) -> VerifyTemplate:
    return VerifyTemplate(
        verify_id=verify_id, type=type, name=name,
        namespace=namespace, cluster_scope=cluster_scope, **kw,
    )


def _img(requested_image, image_status=ImageStatus.RESOLVED,
         resolved_image=None, existence_check_passed=True, **kw) -> ImageResolutionResult:
    return ImageResolutionResult(
        image_intent=requested_image.split("/")[-1].split(":")[0],
        requested_image=requested_image,
        resolved_image=resolved_image or f"172.16.100.1:5000/{requested_image}",
        image_status=image_status,
        existence_check_passed=existence_check_passed,
        **kw,
    )


def _cleanup(cluster_resources=None) -> CleanupSpec:
    return CleanupSpec(
        namespace_cleanup=CleanupNamespace(),
        cluster_scoped_resources=cluster_resources or [],
    )


_UNSET = object()


def _draft(steps=_UNSET, images=None, cleanup=_UNSET, **kw) -> LabDraft:
    return LabDraft(
        source_article_id="art-1",
        title="Test Lab",
        description="desc",
        estimated_duration_minutes=30,
        runtime_requirements=RuntimeRequirements(),
        steps=steps if steps is not _UNSET else [_step()],
        cleanup=cleanup if cleanup is not _UNSET else _cleanup(),
        image_resolution=images or [],
        **kw,
    )


def _passed_ids(results) -> set[str]:
    return {r.check_id for r in results if r.status == ValidatorStatus.PASSED}


def _failed_ids(results) -> set[str]:
    return {r.check_id for r in results if r.status == ValidatorStatus.FAILED}


def _blocking_levels(results, check_id) -> list[BlockingLevel]:
    return [r.blocking_level for r in results if r.check_id == check_id and r.status == ValidatorStatus.FAILED]


validator = StaticValidator()


# ---------------------------------------------------------------------------
# image.no_latest_tag
# ---------------------------------------------------------------------------


class TestImageNoLatestTag:
    def test_pass_pinned_tag(self):
        draft = _draft(images=[_img("nginx:1.25")])
        results = validator.validate(draft)
        assert "image.no_latest_tag" in _passed_ids(results)

    def test_pass_internal_registry_pinned(self):
        draft = _draft(images=[_img("172.16.100.1:5000/nginx:1.25-alpine")])
        results = validator.validate(draft)
        assert "image.no_latest_tag" in _passed_ids(results)

    def test_pass_no_images(self):
        draft = _draft(images=[])
        results = validator.validate(draft)
        assert "image.no_latest_tag" in _passed_ids(results)

    def test_fail_latest_tag(self):
        draft = _draft(images=[_img("nginx:latest", image_status=ImageStatus.BLOCKED, existence_check_passed=None)])
        results = validator.validate(draft)
        assert "image.no_latest_tag" in _failed_ids(results)
        assert BlockingLevel.PUBLISH_BLOCKING in _blocking_levels(results, "image.no_latest_tag")

    def test_fail_no_tag(self):
        draft = _draft(images=[_img("nginx", image_status=ImageStatus.BLOCKED, existence_check_passed=None)])
        results = validator.validate(draft)
        assert "image.no_latest_tag" in _failed_ids(results)

    def test_fail_no_tag_with_registry(self):
        # "172.16.100.1:5000/nginx" — last segment "nginx" has no ":"
        draft = _draft(images=[_img("172.16.100.1:5000/nginx", image_status=ImageStatus.BLOCKED, existence_check_passed=None)])
        results = validator.validate(draft)
        assert "image.no_latest_tag" in _failed_ids(results)


# ---------------------------------------------------------------------------
# image.no_unknown_registry
# ---------------------------------------------------------------------------


class TestImageNoUnknownRegistry:
    def test_pass_no_images(self):
        draft = _draft(images=[])
        results = validator.validate(draft)
        assert "image.no_unknown_registry" in _passed_ids(results)

    def test_pass_internal_registry(self):
        draft = _draft(images=[_img("172.16.100.1:5000/nginx:1.25")])
        results = validator.validate(draft)
        assert "image.no_unknown_registry" in _passed_ids(results)

    def test_fail_docker_io(self):
        draft = _draft(images=[_img("docker.io/library/nginx:1.25", image_status=ImageStatus.BLOCKED, existence_check_passed=None)])
        results = validator.validate(draft)
        assert "image.no_unknown_registry" in _failed_ids(results)
        assert BlockingLevel.PUBLISH_BLOCKING in _blocking_levels(results, "image.no_unknown_registry")

    def test_fail_ghcr_io(self):
        draft = _draft(images=[_img("ghcr.io/foo/bar:v1", image_status=ImageStatus.BLOCKED, existence_check_passed=None)])
        results = validator.validate(draft)
        assert "image.no_unknown_registry" in _failed_ids(results)

    def test_fail_quay_io(self):
        draft = _draft(images=[_img("quay.io/foo/bar:v1", image_status=ImageStatus.BLOCKED, existence_check_passed=None)])
        results = validator.validate(draft)
        assert "image.no_unknown_registry" in _failed_ids(results)

    def test_fail_gcr_io(self):
        draft = _draft(images=[_img("gcr.io/foo/bar:v1", image_status=ImageStatus.BLOCKED, existence_check_passed=None)])
        results = validator.validate(draft)
        assert "image.no_unknown_registry" in _failed_ids(results)


# ---------------------------------------------------------------------------
# image.all_resolved
# ---------------------------------------------------------------------------


class TestImageAllResolved:
    def test_pass_all_resolved(self):
        draft = _draft(images=[_img("nginx:1.25")])
        results = validator.validate(draft)
        assert "image.all_resolved" in _passed_ids(results)

    def test_pass_empty(self):
        draft = _draft(images=[])
        results = validator.validate(draft)
        assert "image.all_resolved" in _passed_ids(results)

    def test_fail_unresolved(self):
        draft = _draft(images=[_img("unknown-tool:1.0", image_status=ImageStatus.UNRESOLVED, existence_check_passed=None)])
        results = validator.validate(draft)
        assert "image.all_resolved" in _failed_ids(results)
        assert BlockingLevel.PUBLISH_BLOCKING in _blocking_levels(results, "image.all_resolved")

    def test_fail_blocked(self):
        draft = _draft(images=[_img("nginx:latest", image_status=ImageStatus.BLOCKED, existence_check_passed=None)])
        results = validator.validate(draft)
        assert "image.all_resolved" in _failed_ids(results)


# ---------------------------------------------------------------------------
# image.all_exist_in_registry
# ---------------------------------------------------------------------------


class TestImageAllExistInRegistry:
    def test_pass_all_checked(self):
        draft = _draft(images=[_img("nginx:1.25", existence_check_passed=True)])
        results = validator.validate(draft)
        assert "image.all_exist_in_registry" in _passed_ids(results)

    def test_pass_empty(self):
        draft = _draft(images=[])
        results = validator.validate(draft)
        assert "image.all_exist_in_registry" in _passed_ids(results)

    def test_fail_not_checked(self):
        draft = _draft(images=[_img("nginx:1.25", existence_check_passed=None)])
        results = validator.validate(draft)
        assert "image.all_exist_in_registry" in _failed_ids(results)
        assert BlockingLevel.PUBLISH_BLOCKING in _blocking_levels(results, "image.all_exist_in_registry")

    def test_fail_check_failed(self):
        draft = _draft(images=[_img("nginx:1.25", existence_check_passed=False)])
        results = validator.validate(draft)
        assert "image.all_exist_in_registry" in _failed_ids(results)

    def test_skip_unresolved_images(self):
        # Unresolved images are not checked for existence (existence check is only for resolved)
        draft = _draft(images=[_img("unknown:1.0", image_status=ImageStatus.UNRESOLVED, existence_check_passed=None)])
        results = validator.validate(draft)
        assert "image.all_exist_in_registry" in _passed_ids(results)


# ---------------------------------------------------------------------------
# explain.verified_if_published
# ---------------------------------------------------------------------------


class TestExplainVerifiedIfPublished:
    def test_pass_not_published(self):
        step = _step(explain=_explain(published_to_student=False))
        draft = _draft(steps=[step])
        results = validator.validate(draft)
        assert "explain.verified_if_published" in _passed_ids(results)

    def test_pass_published_and_verified(self):
        step = _step(explain=_explain(published_to_student=True, admin_verified=True))
        draft = _draft(steps=[step])
        results = validator.validate(draft)
        assert "explain.verified_if_published" in _passed_ids(results)

    def test_fail_published_not_verified(self):
        step = _step(explain=_explain(published_to_student=True, admin_verified=False))
        draft = _draft(steps=[step])
        results = validator.validate(draft)
        assert "explain.verified_if_published" in _failed_ids(results)
        assert BlockingLevel.PUBLISH_BLOCKING in _blocking_levels(results, "explain.verified_if_published")


# ---------------------------------------------------------------------------
# namespace.no_hardcoded
# ---------------------------------------------------------------------------


class TestNamespaceNoHardcoded:
    def test_pass_lab_namespace_placeholder(self):
        vt = _vt(namespace="{{lab_namespace}}")
        draft = _draft(steps=[_step(verify=[vt])])
        results = validator.validate(draft)
        assert "namespace.no_hardcoded" in _passed_ids(results)

    def test_pass_no_verify(self):
        draft = _draft(steps=[_step(verify=[])])
        results = validator.validate(draft)
        assert "namespace.no_hardcoded" in _passed_ids(results)

    def test_fail_default_namespace(self):
        vt = _vt(namespace="default")
        draft = _draft(steps=[_step(verify=[vt])])
        results = validator.validate(draft)
        assert "namespace.no_hardcoded" in _failed_ids(results)
        assert BlockingLevel.PUBLISH_BLOCKING in _blocking_levels(results, "namespace.no_hardcoded")

    def test_fail_kube_system(self):
        vt = _vt(namespace="kube-system")
        draft = _draft(steps=[_step(verify=[vt])])
        results = validator.validate(draft)
        assert "namespace.no_hardcoded" in _failed_ids(results)

    def test_fail_demo_namespace(self):
        vt = _vt(namespace="demo")
        draft = _draft(steps=[_step(verify=[vt])])
        results = validator.validate(draft)
        assert "namespace.no_hardcoded" in _failed_ids(results)


# ---------------------------------------------------------------------------
# verify.no_shell_commands
# ---------------------------------------------------------------------------


class TestVerifyNoShellCommands:
    def test_pass_valid_type(self):
        draft = _draft(steps=[_step(verify=[_vt(type=VerifyType.POD_RUNNING)])])
        results = validator.validate(draft)
        assert "verify.no_shell_commands" in _passed_ids(results)

    def test_pass_no_verify(self):
        draft = _draft(steps=[_step(verify=[])])
        results = validator.validate(draft)
        assert "verify.no_shell_commands" in _passed_ids(results)


# ---------------------------------------------------------------------------
# verify.no_secret_value
# ---------------------------------------------------------------------------


class TestVerifyNoSecretValue:
    def test_pass_valid_type(self):
        draft = _draft(steps=[_step(verify=[_vt(type=VerifyType.SECRET_EXISTS)])])
        results = validator.validate(draft)
        assert "verify.no_secret_value" in _passed_ids(results)

    def test_pass_no_verify(self):
        draft = _draft(steps=[_step(verify=[])])
        results = validator.validate(draft)
        assert "verify.no_secret_value" in _passed_ids(results)


# ---------------------------------------------------------------------------
# cleanup.declared
# ---------------------------------------------------------------------------


class TestCleanupDeclared:
    def test_pass_with_cleanup(self):
        draft = _draft(cleanup=_cleanup())
        results = validator.validate(draft)
        assert "cleanup.declared" in _passed_ids(results)

    def test_fail_no_cleanup(self):
        draft = _draft(cleanup=None)
        results = validator.validate(draft)
        assert "cleanup.declared" in _failed_ids(results)
        assert BlockingLevel.PUBLISH_BLOCKING in _blocking_levels(results, "cleanup.declared")


# ---------------------------------------------------------------------------
# cluster_scoped.cleanup_declared
# ---------------------------------------------------------------------------


class TestClusterScopedCleanupDeclared:
    def test_pass_no_cluster_resources(self):
        draft = _draft(cleanup=_cleanup(cluster_resources=[]))
        results = validator.validate(draft)
        assert "cluster_scoped.cleanup_declared" in _passed_ids(results)

    def test_pass_resources_have_cleanup(self):
        res = ClusterScopedResource(
            kind="ClusterRole", name="demo-reader",
            api_group="rbac.authorization.k8s.io", cleanup="delete",
        )
        draft = _draft(cleanup=_cleanup(cluster_resources=[res]))
        results = validator.validate(draft)
        assert "cluster_scoped.cleanup_declared" in _passed_ids(results)

    def test_pass_no_cleanup_spec(self):
        # If cleanup is None, cluster_scoped check passes vacuously
        draft = _draft(cleanup=None)
        results = validator.validate(draft)
        assert "cluster_scoped.cleanup_declared" in _passed_ids(results)

    def test_fail_resource_missing_cleanup(self):
        res = ClusterScopedResource(
            kind="ClusterRole", name="demo-reader",
            api_group="rbac.authorization.k8s.io", cleanup=None,
        )
        draft = _draft(cleanup=_cleanup(cluster_resources=[res]))
        results = validator.validate(draft)
        assert "cluster_scoped.cleanup_declared" in _failed_ids(results)
        assert BlockingLevel.PUBLISH_BLOCKING in _blocking_levels(results, "cluster_scoped.cleanup_declared")


# ---------------------------------------------------------------------------
# helm.no_generation
# ---------------------------------------------------------------------------


class TestHelmNoGeneration:
    def test_pass_no_helm(self):
        draft = _draft(steps=[_step(commands=["kubectl apply -f deploy.yaml"])])
        results = validator.validate(draft)
        assert "helm.no_generation" in _passed_ids(results)

    def test_fail_helm_install(self):
        draft = _draft(steps=[_step(commands=["helm install my-app ./chart"])])
        results = validator.validate(draft)
        assert "helm.no_generation" in _failed_ids(results)
        assert BlockingLevel.REVIEW_REQUIRED in _blocking_levels(results, "helm.no_generation")

    def test_fail_helm_upgrade(self):
        draft = _draft(steps=[_step(commands=["helm upgrade --install my-app ./chart"])])
        results = validator.validate(draft)
        assert "helm.no_generation" in _failed_ids(results)

    def test_pass_helm_list(self):
        # "helm list" is ok — only install/upgrade are blocked
        draft = _draft(steps=[_step(commands=["helm list -n default"])])
        results = validator.validate(draft)
        assert "helm.no_generation" in _passed_ids(results)


# ---------------------------------------------------------------------------
# service.nodeport
# ---------------------------------------------------------------------------


class TestServiceNodePort:
    def test_pass_no_nodeport(self):
        cmd = "kubectl expose deployment nginx --port=80 --type=ClusterIP"
        draft = _draft(steps=[_step(commands=[cmd])])
        results = validator.validate(draft)
        assert "service.nodeport" in _passed_ids(results)

    def test_fail_nodeport_type_flag(self):
        cmd = "kubectl expose deployment nginx --port=80 --type=NodePort"
        draft = _draft(steps=[_step(commands=[cmd])])
        results = validator.validate(draft)
        assert "service.nodeport" in _failed_ids(results)
        assert BlockingLevel.REVIEW_REQUIRED in _blocking_levels(results, "service.nodeport")

    def test_fail_nodeport_in_yaml(self):
        cmd = "kubectl apply -f - <<EOF\nkind: Service\nspec:\n  type: NodePort\nEOF"
        draft = _draft(steps=[_step(commands=[cmd])])
        results = validator.validate(draft)
        assert "service.nodeport" in _failed_ids(results)


# ---------------------------------------------------------------------------
# operator.crd
# ---------------------------------------------------------------------------


class TestOperatorCrd:
    def test_pass_no_crd(self):
        draft = _draft(steps=[_step(commands=["kubectl apply -f deploy.yaml"])])
        results = validator.validate(draft)
        assert "operator.crd" in _passed_ids(results)

    def test_fail_crd_kind(self):
        cmd = "kubectl apply -f - <<EOF\nkind: CustomResourceDefinition\nEOF"
        draft = _draft(steps=[_step(commands=[cmd])])
        results = validator.validate(draft)
        assert "operator.crd" in _failed_ids(results)
        assert BlockingLevel.REVIEW_REQUIRED in _blocking_levels(results, "operator.crd")


# ---------------------------------------------------------------------------
# pollution.known  +  derived pollution_level
# ---------------------------------------------------------------------------


class TestPollutionLevel:
    def test_namespace_only_by_default(self):
        draft = _draft(steps=[_step(commands=["kubectl apply -f deploy.yaml"])])
        results = validator.validate(draft)
        assert draft.pollution_level == PollutionLevel.NAMESPACE_ONLY
        assert "pollution.known" in _passed_ids(results)

    def test_cluster_scoped_from_yaml(self):
        cmd = "kubectl apply -f - <<EOF\nkind: ClusterRole\nEOF"
        draft = _draft(steps=[_step(commands=[cmd])])
        validator.validate(draft)
        assert draft.pollution_level == PollutionLevel.CLUSTER_SCOPED

    def test_cluster_scoped_from_cleanup_resources(self):
        res = ClusterScopedResource(
            kind="ClusterRole", name="x", api_group="rbac.authorization.k8s.io", cleanup="delete"
        )
        draft = _draft(cleanup=_cleanup(cluster_resources=[res]))
        validator.validate(draft)
        assert draft.pollution_level == PollutionLevel.CLUSTER_SCOPED

    def test_node_level_hostpath(self):
        cmd = "kubectl apply -f - <<EOF\nhostPath:\n  path: /tmp\nEOF"
        draft = _draft(steps=[_step(commands=[cmd])])
        validator.validate(draft)
        assert draft.pollution_level == PollutionLevel.NODE_LEVEL

    def test_node_level_takes_precedence_over_cluster(self):
        cmd = "kubectl apply -f - <<EOF\nkind: ClusterRole\nhostPath:\n  path: /tmp\nEOF"
        draft = _draft(steps=[_step(commands=[cmd])])
        validator.validate(draft)
        assert draft.pollution_level == PollutionLevel.NODE_LEVEL

    def test_fail_unknown_pollution_on_empty_steps(self):
        # No steps → UNKNOWN → publish_blocking
        draft = _draft(steps=[])
        results = validator.validate(draft)
        assert draft.pollution_level == PollutionLevel.UNKNOWN
        assert "pollution.known" in _failed_ids(results)
        assert BlockingLevel.PUBLISH_BLOCKING in _blocking_levels(results, "pollution.known")

    def test_runtime_requirements_updated(self):
        draft = _draft()
        validator.validate(draft)
        assert draft.runtime_requirements.pollution_level == draft.pollution_level


# ---------------------------------------------------------------------------
# shared_namespace_candidate derivation
# ---------------------------------------------------------------------------


class TestSharedNamespaceCandidate:
    def test_true_clean_namespace_lab(self):
        draft = _draft(
            steps=[_step(
                commands=["kubectl apply -f deploy.yaml"],
                verify=[_vt()],
            )],
            images=[_img("nginx:1.25")],
        )
        validator.validate(draft)
        assert draft.shared_namespace_candidate is True
        assert draft.shared_namespace_candidate_reason == ""

    def test_false_cluster_scope_verify(self):
        vt = _vt(cluster_scope=True)
        draft = _draft(steps=[_step(verify=[vt])])
        validator.validate(draft)
        assert draft.shared_namespace_candidate is False
        assert "cluster_scope=true" in draft.shared_namespace_candidate_reason

    def test_false_nodeport(self):
        draft = _draft(steps=[_step(commands=["kubectl expose deploy --type=NodePort"])])
        validator.validate(draft)
        assert draft.shared_namespace_candidate is False
        assert "NodePort" in draft.shared_namespace_candidate_reason

    def test_false_ingress(self):
        cmd = "kubectl apply -f - <<EOF\nkind: Ingress\nEOF"
        draft = _draft(steps=[_step(commands=[cmd])])
        validator.validate(draft)
        assert draft.shared_namespace_candidate is False
        assert "Ingress" in draft.shared_namespace_candidate_reason

    def test_false_pvc(self):
        cmd = "kubectl apply -f - <<EOF\nkind: PersistentVolumeClaim\nEOF"
        draft = _draft(steps=[_step(commands=[cmd])])
        validator.validate(draft)
        assert draft.shared_namespace_candidate is False
        assert "PVC" in draft.shared_namespace_candidate_reason

    def test_false_helm(self):
        draft = _draft(steps=[_step(commands=["helm install foo ./chart"])])
        validator.validate(draft)
        assert draft.shared_namespace_candidate is False
        assert "helm" in draft.shared_namespace_candidate_reason

    def test_false_unresolved_image(self):
        draft = _draft(images=[_img("mystery:1.0", image_status=ImageStatus.UNRESOLVED, existence_check_passed=None)])
        validator.validate(draft)
        assert draft.shared_namespace_candidate is False
        assert "not resolved" in draft.shared_namespace_candidate_reason

    def test_runtime_requirements_updated(self):
        draft = _draft()
        validator.validate(draft)
        assert draft.runtime_requirements.shared_namespace_candidate == draft.shared_namespace_candidate
        assert draft.runtime_requirements.shared_namespace_candidate_reason == draft.shared_namespace_candidate_reason


# ---------------------------------------------------------------------------
# Integration: all publish-blocking checks combined
# ---------------------------------------------------------------------------


class TestPublishGateIntegration:
    def _all_publish_blocking(self, results) -> list[str]:
        return [r.check_id for r in results
                if r.status == ValidatorStatus.FAILED
                and r.blocking_level == BlockingLevel.PUBLISH_BLOCKING]

    def test_clean_draft_has_no_publish_blocking_failures(self):
        draft = _draft(
            steps=[_step(
                commands=["kubectl apply -f deploy.yaml"],
                verify=[_vt()],
                explain=_explain(published_to_student=False),
            )],
            cleanup=_cleanup(),
            images=[_img("nginx:1.25")],
        )
        results = validator.validate(draft)
        blocking = self._all_publish_blocking(results)
        assert blocking == [], f"Unexpected publish_blocking failures: {blocking}"

    def test_dirty_draft_accumulates_failures(self):
        draft = _draft(
            steps=[_step(
                commands=["kubectl expose deploy --type=NodePort"],
                verify=[_vt(namespace="default")],
                explain=_explain(published_to_student=True, admin_verified=False),
            )],
            cleanup=None,
            images=[_img("nginx:latest", image_status=ImageStatus.BLOCKED, existence_check_passed=None)],
        )
        results = validator.validate(draft)
        blocking = set(self._all_publish_blocking(results))
        # At minimum these must be present
        assert "image.no_latest_tag" in blocking
        assert "image.all_resolved" in blocking
        assert "cleanup.declared" in blocking
        assert "namespace.no_hardcoded" in blocking
        assert "explain.verified_if_published" in blocking
