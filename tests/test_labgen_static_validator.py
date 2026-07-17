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


# ---------------------------------------------------------------------------
# commands.executor_compatible
# ---------------------------------------------------------------------------


class TestCommandsExecutorCompatible:
    """Regression suite for publish-gate check: commands.executor_compatible.

    Today's bugs that this gate would have caught at publish time:
      - step-3/4: POD_NAME=$(...) shell variable syntax
      - step-3/4: -o jsonpath blocked output format
      - step-7: kubectl delete namespace blocked cluster-scoped pattern
    """

    def test_pass_empty_commands(self):
        draft = _draft(steps=[_step(commands=[])])
        results = validator.validate(draft)
        assert "commands.executor_compatible" in _passed_ids(results)

    def test_pass_valid_kubectl_commands(self):
        draft = _draft(steps=[_step(commands=[
            "kubectl get pods",
            "kubectl describe pods -l app=crash-demo",
            "kubectl logs -l app=crash-demo",
            "kubectl logs -l app=crash-demo --previous",
            "kubectl delete deployment crash-demo",
            "kubectl rollout status deployment/crash-demo --timeout=90s",
        ])])
        results = validator.validate(draft)
        assert "commands.executor_compatible" in _passed_ids(results)

    def test_pass_namespace_placeholder_substituted(self):
        draft = _draft(steps=[_step(commands=[
            "kubectl get pods -n {{lab_namespace}}",
            "kubectl create deployment crash-demo -n {{lab_namespace}} --image=172.16.100.1:5000/library/busybox:latest -- /bin/sh -c 'echo hi'",
        ])])
        results = validator.validate(draft)
        assert "commands.executor_compatible" in _passed_ids(results)

    def test_fail_shell_variable_assignment(self):
        # Regression: step-3/4 used POD_NAME=$(kubectl ...) — blocked by executor
        draft = _draft(steps=[_step(step_id="step-3", commands=[
            "POD_NAME=$(kubectl get pods -l app=crash-demo -o jsonpath='{.items[0].metadata.name}')",
        ])])
        results = validator.validate(draft)
        assert "commands.executor_compatible" in _failed_ids(results)
        assert _blocking_levels(results, "commands.executor_compatible") == [BlockingLevel.PUBLISH_BLOCKING]

    def test_fail_jsonpath_output_format(self):
        # Regression: -o jsonpath is not in _ALLOWED_OUTPUT_FORMATS
        draft = _draft(steps=[_step(commands=[
            "kubectl get pods -l app=crash-demo -o jsonpath='{.items[0].metadata.name}'",
        ])])
        results = validator.validate(draft)
        assert "commands.executor_compatible" in _failed_ids(results)

    def test_fail_kubectl_delete_namespace(self):
        # Regression: step-7 used kubectl delete namespace — blocked by cluster-scoped pattern
        draft = _draft(steps=[_step(step_id="step-7", commands=[
            "kubectl delete namespace {{lab_namespace}} --wait=true",
        ])])
        results = validator.validate(draft)
        assert "commands.executor_compatible" in _failed_ids(results)

    def test_fail_reports_step_id_in_message(self):
        draft = _draft(steps=[_step(step_id="step-3", commands=[
            "POD_NAME=$(kubectl get pods)",
        ])])
        results = validator.validate(draft)
        failed = [r for r in results if r.check_id == "commands.executor_compatible" and r.status.value == "failed"]
        assert any("step-3" in r.message for r in failed)

    def test_fail_multiple_bad_commands_all_reported(self):
        draft = _draft(steps=[
            _step(step_id="step-3", commands=[
                "POD_NAME=$(kubectl get pods -l app=crash-demo -o jsonpath='{.items[0].metadata.name}')",
                "kubectl describe pod \"$POD_NAME\"",
            ]),
            _step(step_id="step-7", commands=[
                "kubectl delete namespace {{lab_namespace}} --wait=true",
            ]),
        ])
        results = validator.validate(draft)
        failed = [r for r in results if r.check_id == "commands.executor_compatible" and r.status.value == "failed"]
        assert len(failed) == 2  # POD_NAME=$(...) and delete namespace are blocked


# ---------------------------------------------------------------------------
# commands.rbac_coverage
# ---------------------------------------------------------------------------


class TestCommandsRbacCoverage:
    """Regression suite for publish-gate check: commands.rbac_coverage.

    Today's bug that this gate would have caught:
      - step-4: kubectl logs requires pods/log:get — not in original learner Role
    """

    def test_pass_empty_commands(self):
        draft = _draft(steps=[_step(commands=[])])
        results = validator.validate(draft)
        assert "commands.rbac_coverage" in _passed_ids(results)

    def test_pass_kubectl_logs_has_pods_log(self):
        # Regression: kubectl logs needs pods/log:get — must pass after fix
        draft = _draft(steps=[_step(commands=[
            "kubectl logs -l app=crash-demo",
            "kubectl logs -l app=crash-demo --previous",
        ])])
        results = validator.validate(draft)
        assert "commands.rbac_coverage" in _passed_ids(results)

    def test_pass_common_lab_commands_within_role(self):
        draft = _draft(steps=[_step(commands=[
            "kubectl create deployment crash-demo --image=172.16.100.1:5000/library/busybox:latest -- sleep 3600",
            "kubectl get pods",
            "kubectl describe pods -l app=crash-demo",
            "kubectl rollout status deployment/crash-demo --timeout=90s",
            "kubectl patch deployment crash-demo --type=json -p='[{\"op\":\"replace\",\"path\":\"/spec/template/spec/containers/0/command\",\"value\":[\"sleep\",\"3600\"]}]'",
            "kubectl delete deployment crash-demo",
        ])])
        results = validator.validate(draft)
        assert "commands.rbac_coverage" in _passed_ids(results)

    def test_pass_service_and_endpoints_commands_within_role(self):
        # Regression (Service-no-Endpoints lab, Lab-to-Article Sprint Day 1):
        # services/endpoints are core to this lab topic and must be granted —
        # previously services were entirely absent from the learner Role, and
        # endpoints wasn't even recognised by _KUBECTL_RESOURCE_MAP (a verifier
        # blind spot: rbac_coverage would silently pass a command that RBAC
        # would actually reject at K8s API level during rehearsal). Note:
        # create/get/describe/delete only — no patch (see next test).
        draft = _draft(steps=[_step(commands=[
            "kubectl create service clusterip web-svc --tcp=80:80",
            "kubectl get endpoints web-svc",
            "kubectl describe service web-svc",
            "kubectl delete service web-svc",
        ])])
        results = validator.validate(draft)
        assert "commands.rbac_coverage" in _passed_ids(results)

    def test_fail_service_patch_not_in_role(self):
        # Deliberate: LEARNER_ALLOWED_PERMISSIONS does NOT grant update/patch
        # on services (see learner_credentials.py comment) — K8s RBAC can't
        # restrict by spec.type, so granting patch would let a learner
        # escalate a ClusterIP Service to NodePort/LoadBalancer via any of
        # several patch syntaxes (five rounds of safety review kept finding
        # new bypasses trying to block this after the fact at the executor
        # layer instead). This check must keep catching it.
        draft = _draft(steps=[_step(commands=[
            "kubectl patch service web-svc --type=json -p='[{\"op\":\"replace\",\"path\":\"/spec/selector\",\"value\":{\"app\":\"web-backend\"}}]'",
        ])])
        results = validator.validate(draft)
        assert "commands.rbac_coverage" in _failed_ids(results)

    def test_fail_secret_patch_not_in_role(self):
        # secrets Role grants create/get/list/watch/delete but not update/patch —
        # still a genuine gap after the services/endpoints extension, proving
        # the check keeps catching real out-of-role commands.
        draft = _draft(steps=[_step(commands=[
            "kubectl patch secret my-secret --type=json -p='[]'",
        ])])
        results = validator.validate(draft)
        assert "commands.rbac_coverage" in _failed_ids(results)
        assert _blocking_levels(results, "commands.rbac_coverage") == [BlockingLevel.PUBLISH_BLOCKING]

    def test_fail_reports_missing_permission_in_message(self):
        draft = _draft(steps=[_step(commands=[
            "kubectl patch secret my-secret --type=json -p='[]'",
        ])])
        results = validator.validate(draft)
        failed = [r for r in results if r.check_id == "commands.rbac_coverage" and r.status.value == "failed"]
        assert any("secrets" in r.message for r in failed)


# ---------------------------------------------------------------------------
# _command_required_permissions (unit tests for the parser)
# ---------------------------------------------------------------------------


class TestCommandRequiredPermissions:
    from backend.labgen.static_validator import _command_required_permissions as _crp  # type: ignore[attr-defined]

    def test_logs_returns_pods_log(self):
        from backend.labgen.static_validator import _command_required_permissions
        perms = _command_required_permissions("kubectl logs -l app=crash-demo")
        assert ("", "pods/log", "get") in perms

    def test_logs_previous_returns_pods_log(self):
        from backend.labgen.static_validator import _command_required_permissions
        perms = _command_required_permissions("kubectl logs -l app=crash-demo --previous")
        assert ("", "pods/log", "get") in perms

    def test_get_pods_returns_pods_get_list(self):
        from backend.labgen.static_validator import _command_required_permissions
        perms = _command_required_permissions("kubectl get pods")
        assert ("", "pods", "get") in perms
        assert ("", "pods", "list") in perms

    def test_describe_pods_with_selector(self):
        from backend.labgen.static_validator import _command_required_permissions
        perms = _command_required_permissions("kubectl describe pods -l app=crash-demo")
        assert ("", "pods", "get") in perms

    def test_delete_deployment(self):
        from backend.labgen.static_validator import _command_required_permissions
        perms = _command_required_permissions("kubectl delete deployment crash-demo")
        assert ("apps", "deployments", "delete") in perms

    def test_rollout_status(self):
        from backend.labgen.static_validator import _command_required_permissions
        perms = _command_required_permissions("kubectl rollout status deployment/crash-demo --timeout=90s")
        assert ("apps", "deployments", "get") in perms

    def test_patch_deployment(self):
        from backend.labgen.static_validator import _command_required_permissions
        perms = _command_required_permissions("kubectl patch deployment crash-demo --type=json -p='[]'")
        assert ("apps", "deployments", "patch") in perms

    def test_namespace_placeholder_handled(self):
        from backend.labgen.static_validator import _command_required_permissions
        perms = _command_required_permissions("kubectl get pods -n {{lab_namespace}}")
        assert ("", "pods", "get") in perms

    def test_non_kubectl_returns_empty(self):
        from backend.labgen.static_validator import _command_required_permissions
        assert _command_required_permissions("POD_NAME=$(kubectl get pods)") == []

    def test_delete_namespace_not_in_resource_map(self):
        from backend.labgen.static_validator import _command_required_permissions
        # namespaces not in _KUBECTL_RESOURCE_MAP — executor blocks it first anyway
        perms = _command_required_permissions("kubectl delete namespace lab-xxx")
        assert perms == []

    def test_get_endpoints_returns_endpoints_get_list(self):
        # Regression: "endpoints" was previously absent from _KUBECTL_RESOURCE_MAP,
        # so this command was silently invisible to rbac_coverage — it would pass
        # static validation and only fail at rehearsal time with a real 403.
        from backend.labgen.static_validator import _command_required_permissions
        perms = _command_required_permissions("kubectl get endpoints web-svc")
        assert ("", "endpoints", "get") in perms
        assert ("", "endpoints", "list") in perms

    def test_describe_service_returns_services_get_list(self):
        from backend.labgen.static_validator import _command_required_permissions
        perms = _command_required_permissions("kubectl describe service web-svc")
        assert ("", "services", "get") in perms

    def test_patch_service_returns_services_patch(self):
        from backend.labgen.static_validator import _command_required_permissions
        perms = _command_required_permissions("kubectl patch service web-svc --type=json -p='[]'")
        assert ("", "services", "patch") in perms


# ---------------------------------------------------------------------------
# verify.type_implemented
# ---------------------------------------------------------------------------


class TestVerifyTypeImplemented:
    """Regression (Service-no-Endpoints lab, Lab-to-Article Sprint Day 1):
    VerifyType.POD_READY is a valid schema enum value (models.py) but was
    never wired up in verifier.py's runtime dispatch (_SUPPORTED_TYPES).
    Using it in a lab draft passed static validation with zero warnings and
    only failed at live rehearsal — permanently stuck on that step with
    error_code=verify_type_not_implemented. This check catches the mismatch
    at publish time instead, the same way commands.rbac_coverage catches
    RBAC mismatches before they reach rehearsal."""

    def test_pass_pod_running_is_implemented(self):
        draft = _draft(steps=[_step(verify=[_vt(type=VerifyType.POD_RUNNING)])])
        results = validator.validate(draft)
        assert "verify.type_implemented" in _passed_ids(results)

    def test_pass_all_currently_implemented_types(self):
        from backend.labgen.verifier import _SUPPORTED_TYPES
        draft = _draft(steps=[
            _step(step_id=f"s-{t.value}", verify=[_vt(verify_id=f"v-{t.value}", type=t)])
            for t in _SUPPORTED_TYPES
        ])
        results = validator.validate(draft)
        assert "verify.type_implemented" in _passed_ids(results)

    def test_pass_service_has_endpoints_is_implemented(self):
        draft = _draft(steps=[_step(verify=[_vt(type=VerifyType.SERVICE_HAS_ENDPOINTS)])])
        results = validator.validate(draft)
        assert "verify.type_implemented" in _passed_ids(results)

    def test_fail_pod_ready_not_implemented(self):
        draft = _draft(steps=[_step(verify=[_vt(type=VerifyType.POD_READY)])])
        results = validator.validate(draft)
        assert "verify.type_implemented" in _failed_ids(results)
        assert _blocking_levels(results, "verify.type_implemented") == [BlockingLevel.PUBLISH_BLOCKING]

    def test_fail_reports_verify_id_and_type_in_message(self):
        draft = _draft(steps=[_step(verify=[_vt(verify_id="v-broken", type=VerifyType.POD_READY)])])
        results = validator.validate(draft)
        failed = [r for r in results if r.check_id == "verify.type_implemented" and r.status.value == "failed"]
        assert any("v-broken" in r.message and "pod_ready" in r.message for r in failed)

    def test_service_no_endpoints_repair_step_shape_passes(self):
        """Regression (Verifier Gap Fix): mirrors the real published Service-no-
        Endpoints lab's step-6 shape after this fix — service_exists + pod_running
        + service_has_endpoints together on one step, confirming the selector
        repair worked. All three types must validate cleanly together."""
        draft = _draft(steps=[
            _step(verify=[
                _vt(verify_id="v1", type=VerifyType.SERVICE_EXISTS, name="web-svc"),
                _vt(verify_id="v2", type=VerifyType.POD_RUNNING, name="web-backend"),
                _vt(verify_id="v3", type=VerifyType.SERVICE_HAS_ENDPOINTS, name="web-svc"),
            ])
        ])
        results = validator.validate(draft)
        assert "verify.type_implemented" in _passed_ids(results)


class TestVerifyConfigmapValueEqualsFields:
    """ConfigMap-not-effective lab (Second Wave #1): configmap_value_equals reads
    VerifyTemplate.config_key/expected_value, both Optional on the schema since
    only this type uses them. A draft missing either would pass schema
    validation but silently always fail at rehearsal (comparing the ConfigMap's
    real value against "" instead of the intended expected_value)."""

    def test_pass_when_both_fields_present(self):
        draft = _draft(steps=[_step(verify=[
            _vt(type=VerifyType.CONFIGMAP_VALUE_EQUALS, name="app-config",
                config_key="APP_MODE", expected_value="new"),
        ])])
        results = validator.validate(draft)
        assert "verify.configmap_value_equals_fields" in _passed_ids(results)

    def test_fail_when_config_key_missing(self):
        draft = _draft(steps=[_step(verify=[
            _vt(type=VerifyType.CONFIGMAP_VALUE_EQUALS, name="app-config",
                expected_value="new"),
        ])])
        results = validator.validate(draft)
        assert "verify.configmap_value_equals_fields" in _failed_ids(results)
        assert _blocking_levels(results, "verify.configmap_value_equals_fields") == [BlockingLevel.PUBLISH_BLOCKING]

    def test_fail_when_expected_value_missing(self):
        draft = _draft(steps=[_step(verify=[
            _vt(type=VerifyType.CONFIGMAP_VALUE_EQUALS, name="app-config",
                config_key="APP_MODE"),
        ])])
        results = validator.validate(draft)
        assert "verify.configmap_value_equals_fields" in _failed_ids(results)

    def test_fail_when_both_missing(self):
        draft = _draft(steps=[_step(verify=[
            _vt(type=VerifyType.CONFIGMAP_VALUE_EQUALS, name="app-config"),
        ])])
        results = validator.validate(draft)
        assert "verify.configmap_value_equals_fields" in _failed_ids(results)

    def test_pass_when_expected_value_is_legitimately_empty_string(self):
        """A ConfigMap key can legitimately be expected to equal "" — that is
        a real, distinct value from "not set" (None) and must not be treated
        as a missing field."""
        draft = _draft(steps=[_step(verify=[
            _vt(type=VerifyType.CONFIGMAP_VALUE_EQUALS, name="app-config",
                config_key="APP_MODE", expected_value=""),
        ])])
        results = validator.validate(draft)
        assert "verify.configmap_value_equals_fields" in _passed_ids(results)

    def test_other_types_unaffected(self):
        """A draft with no configmap_value_equals verify steps should pass
        this check by default (nothing to check)."""
        draft = _draft(steps=[_step(verify=[_vt(type=VerifyType.POD_RUNNING)])])
        results = validator.validate(draft)
        assert "verify.configmap_value_equals_fields" in _passed_ids(results)

    def test_deployment_restart_types_need_no_extra_fields(self):
        """Unlike configmap_value_equals, the restart-annotation types only
        need namespace/name (already required fields) — no config_key/
        expected_value, so they must validate cleanly with zero extra setup."""
        draft = _draft(steps=[_step(verify=[
            _vt(type=VerifyType.DEPLOYMENT_RESTART_NOT_TRIGGERED, name="demo"),
            _vt(verify_id="v2", type=VerifyType.DEPLOYMENT_RESTART_TRIGGERED, name="demo"),
        ])])
        results = validator.validate(draft)
        assert "verify.type_implemented" in _passed_ids(results)
        assert "verify.configmap_value_equals_fields" in _passed_ids(results)
        assert "verify.type_implemented" not in _failed_ids(results)
