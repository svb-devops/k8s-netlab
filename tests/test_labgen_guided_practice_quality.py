"""
Guided Practice Quality Iteration — Lab 5 v0.1 tests.

Validates:
  A. Placeholder quality gate (content.no_placeholders in StaticValidator)
  B. Admin PATCH preserves publish_status and article-linked metadata
  C. Reader regression: Lab 5 learner path still works after content update
"""

from __future__ import annotations

from typing import Optional

import pytest
from fastapi.testclient import TestClient

from backend.labgen.models import (
    CleanupNamespace,
    CleanupSpec,
    ExplainField,
    LabDraft,
    LabSessionState,
    LabSessionStatus,
    PublishStatus,
    RuntimeRequirements,
    SessionType,
    Step,
    ValidatorStatus,
    BlockingLevel,
    VerifyTemplate,
    VerifyType,
)
from backend.labgen.static_validator import StaticValidator
from backend.labgen.lab_session_service import (
    LabSessionService,
    PrecheckFailed,
    StubVMTracker,
)
from backend.labgen.namespace_lifecycle import StubNamespaceLifecycleAdapter

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean_step(**overrides) -> Step:
    defaults = dict(
        step_id="step_1",
        order=1,
        why="ConfigMap is the standard K8s object for non-sensitive config.",
        do="kubectl create configmap app-config --from-literal=APP_ENV=production",
        observe="You will see 'configmap/app-config created'.",
        explain=ExplainField(
            concept="ConfigMap stores non-sensitive key-value pairs in etcd.",
            observation="kubectl get configmap app-config shows the entry.",
            confidence="admin_verified",
            admin_verified=True,
            published_to_student=True,
        ),
        verify=[VerifyTemplate(
            verify_id="step_1_v1",
            type=VerifyType.CONFIGMAP_EXISTS,
            namespace="{{lab_namespace}}",
            name="app-config",
        )],
    )
    defaults.update(overrides)
    return Step(**defaults)


def _clean_draft(**overrides) -> LabDraft:
    defaults = dict(
        lab_id="cf019133-3a50-444d-8870-a84c25391cb7",
        source_article_id="aa7c4a99-64a6-405d-bdb6-a4765b105b6d",
        title="Kubernetes ConfigMap 实战：从文章到实验",
        description="通过本实验，你将亲手创建并验证 ConfigMap，体会非敏感配置与代码分离的实践。",
        estimated_duration_minutes=10,
        runtime_requirements=RuntimeRequirements(),
        steps=[_clean_step()],
        cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
        publish_status=PublishStatus.PUBLISHED,
        rehearsal_required=True,
        rehearsal_completed=True,
    )
    defaults.update(overrides)
    return LabDraft(**defaults)


def _validator() -> StaticValidator:
    return StaticValidator()


# ---------------------------------------------------------------------------
# A. Placeholder quality gate
# ---------------------------------------------------------------------------


class TestPlaceholderQualityGate:

    def test_clean_draft_passes(self):
        draft = _clean_draft()
        results = _validator().validate(draft)
        gate = [r for r in results if r.check_id == "content.no_placeholders"]
        assert len(gate) == 1
        assert gate[0].status == ValidatorStatus.PASSED

    def test_todo_in_title_fails(self):
        draft = _clean_draft(title="[TODO: Untitled Lab]")
        results = _validator().validate(draft)
        fails = [r for r in results
                 if r.check_id == "content.no_placeholders"
                 and r.status == ValidatorStatus.FAILED]
        assert fails, "Expected failure for [TODO] in title"
        assert any("title" in f.field_path for f in fails)

    def test_todo_in_description_fails(self):
        draft = _clean_draft(description="[TODO: Add description]")
        results = _validator().validate(draft)
        fails = [r for r in results
                 if r.check_id == "content.no_placeholders"
                 and r.status == ValidatorStatus.FAILED]
        assert fails
        assert any("description" in f.field_path for f in fails)

    def test_todo_in_step_why_fails(self):
        step = _clean_step(why="[TODO: explain why this step matters]")
        draft = _clean_draft(steps=[step])
        results = _validator().validate(draft)
        fails = [r for r in results
                 if r.check_id == "content.no_placeholders"
                 and r.status == ValidatorStatus.FAILED]
        assert fails
        assert any("why" in f.field_path for f in fails)

    def test_todo_in_step_observe_fails(self):
        step = _clean_step(observe="[TODO: describe what to observe after completing this step]")
        draft = _clean_draft(steps=[step])
        results = _validator().validate(draft)
        fails = [r for r in results
                 if r.check_id == "content.no_placeholders"
                 and r.status == ValidatorStatus.FAILED]
        assert fails
        assert any("observe" in f.field_path for f in fails)

    def test_todo_in_explain_concept_fails(self):
        step = _clean_step(explain=ExplainField(
            concept="[TODO: core concept]",
            observation="kubectl get configmap shows the entry.",
        ))
        draft = _clean_draft(steps=[step])
        results = _validator().validate(draft)
        fails = [r for r in results
                 if r.check_id == "content.no_placeholders"
                 and r.status == ValidatorStatus.FAILED]
        assert fails
        assert any("explain.concept" in f.field_path for f in fails)

    def test_todo_in_explain_observation_fails(self):
        step = _clean_step(explain=ExplainField(
            concept="ConfigMap stores key-value pairs in etcd.",
            observation="[TODO: expected observation]",
        ))
        draft = _clean_draft(steps=[step])
        results = _validator().validate(draft)
        fails = [r for r in results
                 if r.check_id == "content.no_placeholders"
                 and r.status == ValidatorStatus.FAILED]
        assert fails

    def test_todo_in_verify_notes_fails(self):
        step = _clean_step(verify=[VerifyTemplate(
            verify_id="step_1_v1",
            type=VerifyType.NAMESPACE_EXISTS,
            namespace="{{lab_namespace}}",
            name="{{lab_namespace}}",
            notes="[TODO: configure verifier from article contract]",
        )])
        draft = _clean_draft(steps=[step])
        results = _validator().validate(draft)
        fails = [r for r in results
                 if r.check_id == "content.no_placeholders"
                 and r.status == ValidatorStatus.FAILED]
        assert fails
        assert any("verify" in f.field_path for f in fails)

    def test_placeholder_check_is_publish_blocking(self):
        """[TODO] in any reader-facing field must block publish, not merely warn."""
        draft = _clean_draft(description="[TODO: Add description]")
        results = _validator().validate(draft)
        blocker = next(
            (r for r in results
             if r.check_id == "content.no_placeholders"
             and r.status == ValidatorStatus.FAILED),
            None,
        )
        assert blocker is not None
        assert blocker.blocking_level == BlockingLevel.PUBLISH_BLOCKING

    def test_bare_TODO_word_fails(self):
        """Bare 'TODO' (not bracket-wrapped) also triggers the gate."""
        draft = _clean_draft(description="TODO: fill this in later")
        results = _validator().validate(draft)
        fails = [r for r in results
                 if r.check_id == "content.no_placeholders"
                 and r.status == ValidatorStatus.FAILED]
        assert fails

    def test_multiple_placeholder_fields_all_reported(self):
        """All placeholder violations are reported — not just the first one."""
        step = _clean_step(
            why="[TODO: explain why]",
            observe="[TODO: describe observation]",
        )
        draft = _clean_draft(
            description="[TODO: Add description]",
            steps=[step],
        )
        results = _validator().validate(draft)
        fails = [r for r in results
                 if r.check_id == "content.no_placeholders"
                 and r.status == ValidatorStatus.FAILED]
        assert len(fails) >= 3, f"Expected >= 3 violations, got {len(fails)}"

    def test_lab5_original_stub_content_fails_gate(self):
        """Confirm original stub content (pre-patch) would fail the gate."""
        step_1 = _clean_step(
            why="[TODO: explain why this step matters]",
            observe="[TODO: describe what to observe after completing this step]",
            explain=ExplainField(concept="[TODO: core concept]", observation="[TODO: expected observation]"),
        )
        draft = _clean_draft(
            title="Untitled Lab (from article)",
            description="[TODO: Add description]",
            steps=[step_1],
        )
        results = _validator().validate(draft)
        fails = [r for r in results
                 if r.check_id == "content.no_placeholders"
                 and r.status == ValidatorStatus.FAILED]
        assert len(fails) >= 4, f"Expected >= 4 violations for original stub, got {len(fails)}"

    def test_lab5_patched_content_passes_gate(self):
        """Confirm patched content (post-patch) passes the gate."""
        step_1 = Step(
            step_id="step_1",
            order=1,
            why="ConfigMap 是 Kubernetes 存储非敏感配置的标准对象，将配置与容器镜像解耦。",
            do="kubectl create configmap app-config --from-literal=APP_ENV=production",
            observe="命令执行后你会看到 `configmap/app-config created`，可用 kubectl get configmap 验证。",
            explain=ExplainField(
                concept="ConfigMap 将非敏感的键值对存储在 etcd 中，Pod 通过环境变量或 Volume 消费。",
                observation="输出 configmap/app-config created 表示写入 etcd 成功，DATA 列显示键值对数量。",
                confidence="admin_verified",
                admin_verified=True,
                published_to_student=True,
            ),
            verify=[VerifyTemplate(
                verify_id="step_1_v1",
                type=VerifyType.CONFIGMAP_EXISTS,
                namespace="{{lab_namespace}}",
                name="app-config",
            )],
        )
        step_2 = Step(
            step_id="step_2",
            order=2,
            why="你的实验运行在隔离 namespace 中，与其他学员完全隔离。实验结束后 namespace 自动删除，零残留。",
            do="本步骤由平台自动验证：确认你的实验 namespace 处于活跃状态。",
            observe="平台验证通过表明你的隔离环境运行正常，实验结束后 namespace 自动删除。",
            explain=ExplainField(
                concept="Kubernetes namespace 提供资源隔离的逻辑边界，平台结束时自动 delete namespace。",
                observation="namespace_exists 检查确认 lab namespace 已创建并处于 Active 状态。",
                confidence="admin_verified",
                admin_verified=True,
                published_to_student=True,
            ),
            verify=[VerifyTemplate(
                verify_id="step_2_v1",
                type=VerifyType.NAMESPACE_EXISTS,
                namespace="{{lab_namespace}}",
                name="{{lab_namespace}}",
                manual_review_required=False,
            )],
        )
        draft = _clean_draft(
            title="Kubernetes ConfigMap 实战：从文章到实验",
            description="通过本实验，你将亲手创建并验证 ConfigMap，体会非敏感配置与代码分离的实践。",
            steps=[step_1, step_2],
        )
        results = _validator().validate(draft)
        fails = [r for r in results
                 if r.check_id == "content.no_placeholders"
                 and r.status == ValidatorStatus.FAILED]
        assert not fails, f"Patched content should pass gate, got: {fails}"


# ---------------------------------------------------------------------------
# B. Admin PATCH integrity
# ---------------------------------------------------------------------------


class TestAdminPatchIntegrity:
    """Use dependency_overrides to inject in-memory repos — avoids hitting the live data file."""

    @pytest.fixture
    def _in_mem_draft_repo(self):
        return _MemDraftRepo(drafts=[_clean_draft(publish_status=PublishStatus.PUBLISHED)])

    @pytest.fixture
    def _in_mem_diff_repo(self):
        from backend.labgen.review_diff import AdminReviewDiffRepository

        class _MemDiff:
            def __init__(self): self._store = []
            def append(self, diff): self._store.append(diff)
            def list_by_draft(self, lab_id): return [d for d in self._store if d.lab_draft_id == lab_id]

        return _MemDiff()

    @pytest.fixture
    def admin_client(self, _in_mem_draft_repo, _in_mem_diff_repo):
        from backend.main import app
        from backend.labgen.routes import require_admin_user, get_repository, get_diff_repository

        app.dependency_overrides[require_admin_user] = lambda: "smoke-admin"
        app.dependency_overrides[get_repository] = lambda: _in_mem_draft_repo
        app.dependency_overrides[get_diff_repository] = lambda: _in_mem_diff_repo
        with TestClient(app) as client:
            yield client
        app.dependency_overrides.pop(require_admin_user, None)
        app.dependency_overrides.pop(get_repository, None)
        app.dependency_overrides.pop(get_diff_repository, None)

    @pytest.fixture
    def unauth_client(self, _in_mem_draft_repo):
        from backend.main import app
        from backend.labgen.routes import get_repository

        app.dependency_overrides[get_repository] = lambda: _in_mem_draft_repo
        with TestClient(app) as client:
            yield client
        app.dependency_overrides.pop(get_repository, None)

    def test_patch_title_preserves_publish_status(self, admin_client):
        """PATCH title must not change publish_status from published to draft."""
        lab_id = "cf019133-3a50-444d-8870-a84c25391cb7"
        resp = admin_client.patch(
            f"/api/labgen/drafts/{lab_id}",
            json={"title": "Kubernetes ConfigMap 实战：从文章到实验"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Kubernetes ConfigMap 实战：从文章到实验"
        assert data["publish_status"] == "published", "PATCH must not demote publish_status"

    def test_patch_preserves_article_linked_metadata(self, admin_client):
        """PATCH must not clear source_article_id or rehearsal fields."""
        lab_id = "cf019133-3a50-444d-8870-a84c25391cb7"
        resp = admin_client.patch(
            f"/api/labgen/drafts/{lab_id}",
            json={"description": "Updated description without TODO."},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["source_article_id"] == "aa7c4a99-64a6-405d-bdb6-a4765b105b6d"
        assert data["rehearsal_required"] is True
        assert data["rehearsal_completed"] is True

    def test_patch_rejects_publish_status_published(self, admin_client):
        """Directly setting publish_status=published via PATCH must be rejected."""
        lab_id = "cf019133-3a50-444d-8870-a84c25391cb7"
        resp = admin_client.patch(
            f"/api/labgen/drafts/{lab_id}",
            json={"publish_status": "published"},
        )
        assert resp.status_code == 400

    def test_patch_requires_admin(self, unauth_client):
        """Non-admin PATCH must be rejected."""
        lab_id = "cf019133-3a50-444d-8870-a84c25391cb7"
        resp = unauth_client.patch(
            f"/api/labgen/drafts/{lab_id}",
            json={"title": "hacked title"},
        )
        assert resp.status_code in (401, 403)

    def test_patch_unknown_lab_is_404(self, admin_client):
        resp = admin_client.patch(
            "/api/labgen/drafts/no-such-id",
            json={"title": "anything"},
        )
        assert resp.status_code == 404

    def test_patch_steps_with_real_content_persists(self, admin_client):
        """PATCH with full steps including real why/observe persists correctly."""
        lab_id = "cf019133-3a50-444d-8870-a84c25391cb7"
        new_steps = [
            {
                "schema_version": "1.0",
                "step_id": "step_1",
                "order": 1,
                "why": "ConfigMap 将配置与镜像解耦，允许同一镜像在不同环境复用。",
                "do": "kubectl create configmap app-config --from-literal=APP_ENV=production",
                "commands": [],
                "observe": "看到 configmap/app-config created 说明写入 etcd 成功。",
                "explain": {
                    "concept": "ConfigMap 存储非敏感键值对，与 Secret 不同不做 base64 编码。",
                    "observation": "DATA 列显示 APP_ENV=production。",
                    "confidence": "admin_verified",
                    "admin_verified": True,
                    "published_to_student": True,
                },
                "verify": [{
                    "schema_version": "1.0",
                    "verify_id": "step_1_v1",
                    "type": "configmap_exists",
                    "namespace": "{{lab_namespace}}",
                    "name": "app-config",
                    "label_selector": None,
                    "cluster_scope": False,
                    "supported_runtimes": ["dedicated_vm"],
                    "blocking_level_on_fail": "publish_blocking",
                    "manual_review_required": False,
                    "notes": None,
                }],
            }
        ]
        resp = admin_client.patch(
            f"/api/labgen/drafts/{lab_id}",
            json={"steps": new_steps},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["steps"][0]["why"] == "ConfigMap 将配置与镜像解耦，允许同一镜像在不同环境复用。"
        assert data["steps"][0]["observe"] == "看到 configmap/app-config created 说明写入 etcd 成功。"
        assert data["steps"][0]["explain"]["concept"] == "ConfigMap 存储非敏感键值对，与 Secret 不同不做 base64 编码。"
        assert data["publish_status"] == "published"

    def test_patch_records_diff(self, admin_client):
        """PATCH records an AdminReviewDiff for audit trail."""
        lab_id = "cf019133-3a50-444d-8870-a84c25391cb7"
        # Use a description different from _clean_draft() default to guarantee a change
        admin_client.patch(
            f"/api/labgen/drafts/{lab_id}",
            json={"description": "通过本实验，你将亲手创建并验证 ConfigMap（admin-patched）。"},
        )
        resp = admin_client.get(f"/api/labgen/drafts/{lab_id}/diffs")
        assert resp.status_code == 200
        diffs = resp.json()
        assert len(diffs) >= 1
        field_paths = [c["field_path"] for d in diffs for c in d["changes"]]
        assert "description" in field_paths


# ---------------------------------------------------------------------------
# C. Reader regression
# ---------------------------------------------------------------------------


class _MemDraftRepo:
    def __init__(self, drafts: list[LabDraft] | None = None) -> None:
        self._store: dict[str, LabDraft] = {}
        for d in (drafts or []):
            self._store[d.lab_id] = d

    def get(self, lab_id: str) -> LabDraft | None:
        return self._store.get(lab_id)

    def update(self, draft: LabDraft) -> LabDraft:
        self._store[draft.lab_id] = draft
        return draft

    def create(self, draft: LabDraft) -> LabDraft:
        self._store[draft.lab_id] = draft
        return draft

    def list_all(self) -> list[LabDraft]:
        return list(self._store.values())


class _MemSessionRepo:
    def __init__(self, sessions: list[LabSessionState] | None = None) -> None:
        self._store: dict[str, LabSessionState] = {}
        for s in (sessions or []):
            self._store[s.session_id] = s

    def get(self, session_id: str) -> LabSessionState | None:
        return self._store.get(session_id)

    def create(self, s: LabSessionState) -> LabSessionState:
        self._store[s.session_id] = s
        return s

    def update(self, s: LabSessionState) -> LabSessionState:
        self._store[s.session_id] = s
        return s

    def list_all(self) -> list[LabSessionState]:
        return list(self._store.values())

    def list_by_student(self, username: str) -> list[LabSessionState]:
        return [s for s in self._store.values() if s.student_username == username]


def _make_svc(draft_repo, session_repo=None, vm_tracker=None):
    from backend.labgen.image_resolver import ImageResolver

    sr = session_repo or _MemSessionRepo()
    ns = StubNamespaceLifecycleAdapter()
    vt = vm_tracker or StubVMTracker()

    class _NullImageResolver:
        def needs_recheck(self, img): return False
        def check_registry_existence(self, img): return img

    class _NullRuntimePrecheck:
        def check(self, session, draft): return []

    return LabSessionService(
        draft_repo=draft_repo,
        session_repo=sr,
        vm_tracker=vt,
        ns_lifecycle=ns,
        image_resolver=_NullImageResolver(),
        runtime_precheck=_NullRuntimePrecheck(),
    )


class TestReaderRegressionAfterPatch:

    def _patched_draft(self) -> LabDraft:
        """Lab 5 with real guided practice content (post-patch state)."""
        step_1 = Step(
            step_id="step_1",
            order=1,
            why="ConfigMap 将配置与镜像解耦，允许同一镜像在不同环境复用。",
            do="kubectl create configmap app-config --from-literal=APP_ENV=production",
            observe="看到 configmap/app-config created 说明写入 etcd 成功。",
            explain=ExplainField(
                concept="ConfigMap 存储非敏感键值对，与 Secret 不同不做 base64 编码。",
                observation="DATA 列显示 APP_ENV=production。",
                confidence="admin_verified",
                admin_verified=True,
                published_to_student=True,
            ),
            verify=[VerifyTemplate(
                verify_id="step_1_v1",
                type=VerifyType.CONFIGMAP_EXISTS,
                namespace="{{lab_namespace}}",
                name="app-config",
            )],
        )
        step_2 = Step(
            step_id="step_2",
            order=2,
            why="你的实验运行在隔离 namespace 中，实验结束后自动删除，零残留。",
            do="本步骤由平台自动验证：确认你的实验 namespace 处于活跃状态。",
            observe="平台验证通过表明隔离环境正常，实验结束后 namespace 自动删除。",
            explain=ExplainField(
                concept="Kubernetes namespace 提供资源隔离的逻辑边界，平台结束时自动 delete。",
                observation="namespace_exists 检查确认 lab namespace 处于 Active 状态。",
                confidence="admin_verified",
                admin_verified=True,
                published_to_student=True,
            ),
            verify=[VerifyTemplate(
                verify_id="step_2_v1",
                type=VerifyType.NAMESPACE_EXISTS,
                namespace="{{lab_namespace}}",
                name="{{lab_namespace}}",
                manual_review_required=False,
            )],
        )
        return LabDraft(
            lab_id="cf019133-3a50-444d-8870-a84c25391cb7",
            source_article_id="aa7c4a99-64a6-405d-bdb6-a4765b105b6d",
            title="Kubernetes ConfigMap 实战：从文章到实验",
            description="通过本实验，你将亲手创建并验证 ConfigMap。",
            estimated_duration_minutes=10,
            runtime_requirements=RuntimeRequirements(),
            steps=[step_1, step_2],
            cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
            publish_status=PublishStatus.PUBLISHED,
            rehearsal_required=True,
            rehearsal_completed=True,
        )

    def test_learner_can_start_patched_lab(self):
        """Learner precheck PASSES for patched Lab 5 (published, article-linked)."""
        draft = self._patched_draft()
        dr = _MemDraftRepo(drafts=[draft])
        svc = _make_svc(draft_repo=dr)
        result = svc.run_precheck(draft.lab_id, "401", "learner1")
        assert result.passed, f"Expected precheck PASS, got: {result.failures}"

    def test_catalog_count_unchanged_after_patch(self):
        """Catalog still returns exactly 5 labs after patch (count invariant)."""
        from backend.labgen.learner_catalog import LearnerCatalogService
        from backend.labgen.static_validator import StaticValidator as SV

        patched = self._patched_draft()
        other_drafts = [
            LabDraft(
                lab_id=f"lab-00{i}",
                source_article_id="pilot:k8s-basics",
                title=f"Lab {i}",
                description="Real content, no placeholders.",
                estimated_duration_minutes=10,
                runtime_requirements=RuntimeRequirements(),
                steps=[_clean_step(step_id=f"s{i}")],
                cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
                publish_status=PublishStatus.PUBLISHED,
            )
            for i in range(1, 5)
        ]
        dr = _MemDraftRepo(drafts=other_drafts + [patched])
        sr = _MemSessionRepo()
        catalog_svc = LearnerCatalogService(draft_repo=dr, validator=SV(), session_repo=sr)
        labs = catalog_svc.list_published_labs(actor_user="learner1")
        assert len(labs) == 5

    def test_lab5_not_visible_as_draft_to_learner(self):
        """A draft version of Lab 5 must not appear in the catalog."""
        from backend.labgen.learner_catalog import LearnerCatalogService
        from backend.labgen.static_validator import StaticValidator as SV

        draft_version = self._patched_draft().model_copy(update={"publish_status": PublishStatus.DRAFT})
        dr = _MemDraftRepo(drafts=[draft_version])
        sr = _MemSessionRepo()
        catalog_svc = LearnerCatalogService(draft_repo=dr, validator=SV(), session_repo=sr)
        labs = catalog_svc.list_published_labs(actor_user="learner1")
        assert len(labs) == 0, "Draft Lab 5 must not appear in learner catalog"

    def test_lab5_source_article_id_not_in_catalog(self):
        """source_article_id (raw article reference) must not appear in catalog entry."""
        from backend.labgen.learner_catalog import LearnerCatalogService
        from backend.labgen.static_validator import StaticValidator as SV

        patched = self._patched_draft()
        dr = _MemDraftRepo(drafts=[patched])
        sr = _MemSessionRepo()
        catalog_svc = LearnerCatalogService(draft_repo=dr, validator=SV(), session_repo=sr)
        labs = catalog_svc.list_published_labs(actor_user="learner1")
        assert labs, "Published Lab 5 must appear in catalog"
        lab_dict = labs[0].model_dump()
        assert "source_article_id" not in lab_dict or lab_dict.get("source_article_id") is None, (
            "source_article_id must not be exposed in learner catalog"
        )

    def test_lab5_step_preview_has_real_content(self):
        """Step preview shows real why/observe, no [TODO]."""
        from backend.labgen.learner_catalog import LearnerCatalogService
        from backend.labgen.static_validator import StaticValidator as SV

        patched = self._patched_draft()
        dr = _MemDraftRepo(drafts=[patched])
        sr = _MemSessionRepo()
        catalog_svc = LearnerCatalogService(draft_repo=dr, validator=SV(), session_repo=sr)
        detail = catalog_svc.get_published_lab_detail(patched.lab_id, actor_user="learner1")
        assert detail is not None
        for step_preview in detail.steps_preview:
            summary = step_preview.instructions_summary or ""
            assert "[TODO" not in summary, f"Step preview still contains placeholder: {summary}"

    def test_patched_lab_passes_placeholder_gate(self):
        """StaticValidator content.no_placeholders gate passes on patched Lab 5."""
        draft = self._patched_draft()
        results = _validator().validate(draft)
        fails = [r for r in results
                 if r.check_id == "content.no_placeholders"
                 and r.status == ValidatorStatus.FAILED]
        assert not fails, f"Patched Lab 5 should pass placeholder gate, got: {fails}"

    def test_step2_manual_review_not_required(self):
        """step_2 namespace_exists verify must not have manual_review_required=True."""
        draft = self._patched_draft()
        step2 = next(s for s in draft.steps if s.step_id == "step_2")
        for vt in step2.verify:
            if vt.type == VerifyType.NAMESPACE_EXISTS:
                assert not vt.manual_review_required, (
                    "namespace_exists is auto-verifiable — manual_review_required must be False"
                )
