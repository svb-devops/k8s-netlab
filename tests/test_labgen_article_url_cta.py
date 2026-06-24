"""
G-58: Article URL + CTA Tool tests.

Covers:
  A. Article metadata PATCH (admin only)
  B. CTA generation endpoint (admin only)
  C. Learner exposure rules (article_url safe; source_article_id/raw text never exposed)
  D. Regression (existing 6 published labs unaffected)
"""

from __future__ import annotations

from typing import Optional
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.labgen.models import (
    CleanupNamespace,
    CleanupSpec,
    ExplainField,
    LabDraft,
    PublishStatus,
    RuntimeRequirements,
    Step,
)
from backend.labgen.routes import (
    get_repository,
    require_admin_user,
)
from backend.labgen.learner_catalog import LearnerCatalogService
from backend.labgen.static_validator import StaticValidator

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# In-memory repo
# ---------------------------------------------------------------------------


class _MemRepo:
    def __init__(self) -> None:
        self._store: dict[str, LabDraft] = {}

    def create(self, draft: LabDraft) -> LabDraft:
        self._store[draft.lab_id] = draft
        return draft

    def get(self, lab_id: str) -> Optional[LabDraft]:
        return self._store.get(lab_id)

    def update(self, draft: LabDraft) -> LabDraft:
        self._store[draft.lab_id] = draft
        return draft

    def list_all(self) -> list[LabDraft]:
        return list(self._store.values())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mem_repo() -> _MemRepo:
    return _MemRepo()


@pytest.fixture()
def admin_client(mem_repo):
    from backend.main import app

    app.dependency_overrides[get_repository] = lambda: mem_repo
    app.dependency_overrides[require_admin_user] = lambda: "testadmin"
    c = TestClient(app, raise_server_exceptions=True)
    yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def non_admin_client(mem_repo):
    from backend.main import app
    from backend.auth_deps import get_current_user

    app.dependency_overrides[get_repository] = lambda: mem_repo
    app.dependency_overrides[get_current_user] = lambda: "regularuser"
    c = TestClient(app, raise_server_exceptions=True)
    yield c
    app.dependency_overrides.clear()


def _make_step() -> Step:
    return Step(
        step_id="s1",
        order=1,
        why="why",
        do="do",
        observe="observe",
        explain=ExplainField(concept="c", observation="o"),
    )


def _make_draft(mem_repo, publish_status=PublishStatus.DRAFT, **kw) -> LabDraft:
    draft = LabDraft(
        source_article_id=kw.get("source_article_id", "internal-art-001"),
        title=kw.get("title", "K8s Basics"),
        description=kw.get("description", "Learn K8s"),
        estimated_duration_minutes=kw.get("estimated_duration_minutes", 20),
        runtime_requirements=RuntimeRequirements(),
        steps=[_make_step()],
        cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
        publish_status=publish_status,
        rehearsal_required=False,
        rehearsal_completed=False,
        article_url=kw.get("article_url"),
        article_title=kw.get("article_title"),
        article_channel=kw.get("article_channel"),
        cta_enabled=kw.get("cta_enabled", False),
    )
    mem_repo.create(draft)
    return draft


# ---------------------------------------------------------------------------
# A. Article metadata PATCH tests
# ---------------------------------------------------------------------------


class TestArticleMetadataPatch:
    def test_admin_can_set_article_url(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo)
        r = admin_client.patch(
            f"/api/labgen/drafts/{draft.lab_id}",
            json={"article_url": "https://example.com/my-article"},
        )
        assert r.status_code == 200
        assert r.json()["article_url"] == "https://example.com/my-article"

    def test_admin_can_set_article_title(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo)
        r = admin_client.patch(
            f"/api/labgen/drafts/{draft.lab_id}",
            json={"article_title": "K8s ConfigMap Explained"},
        )
        assert r.status_code == 200
        assert r.json()["article_title"] == "K8s ConfigMap Explained"

    def test_admin_can_set_article_channel_wechat(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo)
        r = admin_client.patch(
            f"/api/labgen/drafts/{draft.lab_id}",
            json={"article_channel": "wechat"},
        )
        assert r.status_code == 200
        assert r.json()["article_channel"] == "wechat"

    def test_admin_can_set_article_channel_official_site(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo)
        r = admin_client.patch(
            f"/api/labgen/drafts/{draft.lab_id}",
            json={"article_channel": "official_site"},
        )
        assert r.status_code == 200

    def test_invalid_article_channel_rejected(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo)
        r = admin_client.patch(
            f"/api/labgen/drafts/{draft.lab_id}",
            json={"article_channel": "<script>evil</script>"},
        )
        assert r.status_code == 422

    def test_unknown_channel_rejected(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo)
        r = admin_client.patch(
            f"/api/labgen/drafts/{draft.lab_id}",
            json={"article_channel": "unknown_platform"},
        )
        assert r.status_code == 422

    def test_admin_can_set_cta_enabled(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo)
        r = admin_client.patch(
            f"/api/labgen/drafts/{draft.lab_id}",
            json={"cta_enabled": True},
        )
        assert r.status_code == 200
        assert r.json()["cta_enabled"] is True

    def test_article_url_with_http_accepted(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo)
        r = admin_client.patch(
            f"/api/labgen/drafts/{draft.lab_id}",
            json={"article_url": "http://blog.example.com/post"},
        )
        assert r.status_code == 200

    def test_invalid_url_scheme_rejected(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo)
        r = admin_client.patch(
            f"/api/labgen/drafts/{draft.lab_id}",
            json={"article_url": "javascript:alert(1)"},
        )
        assert r.status_code == 422

    def test_ftp_url_rejected(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo)
        r = admin_client.patch(
            f"/api/labgen/drafts/{draft.lab_id}",
            json={"article_url": "ftp://files.example.com/article"},
        )
        assert r.status_code == 422

    def test_html_in_title_rejected(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo)
        r = admin_client.patch(
            f"/api/labgen/drafts/{draft.lab_id}",
            json={"article_title": "<script>alert('xss')</script>"},
        )
        assert r.status_code == 422

    def test_tag_in_title_rejected(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo)
        r = admin_client.patch(
            f"/api/labgen/drafts/{draft.lab_id}",
            json={"article_title": "<b>Bold Title</b>"},
        )
        assert r.status_code == 422

    def test_non_admin_cannot_update_metadata(self, non_admin_client, mem_repo):
        draft = _make_draft(mem_repo)
        r = non_admin_client.patch(
            f"/api/labgen/drafts/{draft.lab_id}",
            json={"article_url": "https://example.com/article"},
        )
        assert r.status_code == 403

    def test_metadata_persists_in_repo(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo)
        admin_client.patch(
            f"/api/labgen/drafts/{draft.lab_id}",
            json={
                "article_url": "https://zhihu.com/p/123",
                "article_title": "My Article",
                "article_channel": "zhihu",
                "cta_enabled": True,
            },
        )
        saved = mem_repo.get(draft.lab_id)
        assert saved.article_url == "https://zhihu.com/p/123"
        assert saved.article_title == "My Article"
        assert saved.article_channel == "zhihu"
        assert saved.cta_enabled is True

    def test_existing_labs_without_article_url_remain_compatible(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo)
        r = admin_client.get(f"/api/labgen/drafts/{draft.lab_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["article_url"] is None
        assert data["article_title"] is None
        assert data["cta_enabled"] is False

    def test_null_article_url_accepted(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo, article_url="https://example.com/old")
        r = admin_client.patch(
            f"/api/labgen/drafts/{draft.lab_id}",
            json={"article_url": None},
        )
        assert r.status_code == 200
        assert r.json()["article_url"] is None


# ---------------------------------------------------------------------------
# B. CTA generation endpoint tests
# ---------------------------------------------------------------------------


class TestCTAGeneration:
    def test_published_lab_returns_cta(self, admin_client, mem_repo):
        draft = _make_draft(
            mem_repo,
            publish_status=PublishStatus.PUBLISHED,
            article_url="https://example.com/article",
            article_title="Test Article",
            cta_enabled=True,
        )
        r = admin_client.get(f"/api/labgen/drafts/{draft.lab_id}/cta")
        assert r.status_code == 200

    def test_draft_lab_also_returns_cta_for_admin_preview(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo, publish_status=PublishStatus.DRAFT)
        r = admin_client.get(f"/api/labgen/drafts/{draft.lab_id}/cta")
        assert r.status_code == 200
        assert r.json()["is_published"] is False

    def test_cta_includes_deep_link(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo)
        r = admin_client.get(f"/api/labgen/drafts/{draft.lab_id}/cta")
        data = r.json()
        assert draft.lab_id in data["deep_link"]
        assert "labgen-lab.html" in data["deep_link"]

    def test_cta_lab_url_contains_site_domain(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo)
        r = admin_client.get(f"/api/labgen/drafts/{draft.lab_id}/cta")
        data = r.json()
        assert "lab.cloudnetops.tech" in data["lab_url"]

    def test_cta_includes_article_title(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo, article_title="ConfigMap Basics")
        r = admin_client.get(f"/api/labgen/drafts/{draft.lab_id}/cta")
        data = r.json()
        assert "ConfigMap Basics" in data["markdown_cta"]

    def test_cta_includes_sandbox_wording(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo)
        r = admin_client.get(f"/api/labgen/drafts/{draft.lab_id}/cta")
        data = r.json()
        assert "销毁" in data["copyable_text"] or "destroy" in data["copyable_text"].lower() \
               or "自动" in data["copyable_text"]

    def test_cta_does_not_expose_source_article_id(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo, source_article_id="internal-secret-id")
        r = admin_client.get(f"/api/labgen/drafts/{draft.lab_id}/cta")
        body = r.text
        assert "internal-secret-id" not in body

    def test_cta_does_not_claim_live_llm(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo)
        r = admin_client.get(f"/api/labgen/drafts/{draft.lab_id}/cta")
        body = r.text.lower()
        assert "live llm" not in body
        assert "live ai" not in body

    def test_cta_does_not_claim_public_launch(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo)
        r = admin_client.get(f"/api/labgen/drafts/{draft.lab_id}/cta")
        body = r.text.lower()
        assert "public launch" not in body
        assert "production ready" not in body

    def test_cta_does_not_claim_user_upload(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo)
        r = admin_client.get(f"/api/labgen/drafts/{draft.lab_id}/cta")
        body = r.text.lower()
        assert "upload" not in body
        assert "上传" not in body

    def test_cta_not_found_for_missing_lab(self, admin_client, mem_repo):
        r = admin_client.get("/api/labgen/drafts/nonexistent-id/cta")
        assert r.status_code == 404

    def test_non_admin_cannot_access_cta(self, non_admin_client, mem_repo):
        draft = _make_draft(mem_repo)
        r = non_admin_client.get(f"/api/labgen/drafts/{draft.lab_id}/cta")
        assert r.status_code == 403

    def test_cta_contains_all_four_formats(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo)
        r = admin_client.get(f"/api/labgen/drafts/{draft.lab_id}/cta")
        data = r.json()
        assert "plain_cta" in data
        assert "markdown_cta" in data
        assert "html_cta" in data
        assert "copyable_text" in data

    def test_cta_cta_enabled_reflects_draft(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo, cta_enabled=True, publish_status=PublishStatus.PUBLISHED)
        r = admin_client.get(f"/api/labgen/drafts/{draft.lab_id}/cta")
        assert r.json()["cta_enabled"] is True

    def test_cta_disabled_draft_still_returns_cta_for_admin(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo, cta_enabled=False)
        r = admin_client.get(f"/api/labgen/drafts/{draft.lab_id}/cta")
        assert r.status_code == 200
        assert r.json()["cta_enabled"] is False


# ---------------------------------------------------------------------------
# C. Learner exposure rules
# ---------------------------------------------------------------------------


class TestLearnerExposure:
    def _make_catalog_svc(self, mem_repo):
        return LearnerCatalogService(
            draft_repo=mem_repo,
            validator=StaticValidator(),
        )

    def _published_draft_with_validators(self, mem_repo, **kw) -> LabDraft:
        from backend.labgen.models import (
            BlockingLevel, ValidatorResult, ValidatorStatus,
            ImageResolutionResult, ImageStatus,
        )
        passing_result = ValidatorResult(
            check_id="dummy_pass",
            status=ValidatorStatus.PASSED,
            blocking_level=BlockingLevel.DRAFT_WARNING,
            field_path="",
            message="ok",
        )
        resolved_image = ImageResolutionResult(
            image_intent="nginx:latest",
            requested_image="nginx:latest",
            resolved_image="registry/nginx:latest",
            image_status=ImageStatus.RESOLVED,
        )
        draft = LabDraft(
            source_article_id=kw.get("source_article_id", "internal-id-should-never-leak"),
            title=kw.get("title", "Published Lab"),
            description="desc",
            estimated_duration_minutes=20,
            runtime_requirements=RuntimeRequirements(),
            steps=[_make_step()],
            cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
            publish_status=PublishStatus.PUBLISHED,
            rehearsal_required=False,
            rehearsal_completed=False,
            validator_results=[passing_result],
            image_resolution=[resolved_image],
            article_url=kw.get("article_url"),
            article_title=kw.get("article_title"),
            article_channel=kw.get("article_channel"),
            cta_enabled=kw.get("cta_enabled", False),
        )
        mem_repo.create(draft)
        return draft

    def test_learner_catalog_does_not_expose_source_article_id(self, mem_repo):
        draft = self._published_draft_with_validators(mem_repo)
        svc = self._make_catalog_svc(mem_repo)
        items = svc.list_published_labs(actor_user="learner1")
        assert len(items) >= 1
        item_dict = items[0].model_dump()
        assert "source_article_id" not in item_dict
        assert "internal-id-should-never-leak" not in str(item_dict)

    def test_learner_detail_exposes_article_url_when_cta_enabled(self, mem_repo):
        draft = self._published_draft_with_validators(
            mem_repo,
            article_url="https://zhihu.com/p/123",
            article_title="K8s Article",
            article_channel="zhihu",
            cta_enabled=True,
        )
        svc = self._make_catalog_svc(mem_repo)
        detail = svc.get_published_lab_detail(lab_id=draft.lab_id, actor_user="learner1")
        assert detail is not None
        assert detail.article_url == "https://zhihu.com/p/123"
        assert detail.article_title == "K8s Article"
        assert detail.article_channel == "zhihu"

    def test_learner_detail_hides_article_url_when_cta_disabled(self, mem_repo):
        draft = self._published_draft_with_validators(
            mem_repo,
            article_url="https://zhihu.com/p/123",
            article_title="K8s Article",
            cta_enabled=False,
        )
        svc = self._make_catalog_svc(mem_repo)
        detail = svc.get_published_lab_detail(lab_id=draft.lab_id, actor_user="learner1")
        assert detail is not None
        assert detail.article_url is None
        assert detail.article_title is None

    def test_learner_detail_does_not_expose_source_article_id(self, mem_repo):
        draft = self._published_draft_with_validators(
            mem_repo,
            source_article_id="internal-uuid-never-leak",
            cta_enabled=True,
            article_url="https://example.com",
        )
        svc = self._make_catalog_svc(mem_repo)
        detail = svc.get_published_lab_detail(lab_id=draft.lab_id, actor_user="learner1")
        assert detail is not None
        detail_dict = detail.model_dump()
        assert "source_article_id" not in detail_dict
        assert "internal-uuid-never-leak" not in str(detail_dict)

    def test_learner_detail_no_raw_article_text_field(self, mem_repo):
        draft = self._published_draft_with_validators(mem_repo, cta_enabled=True)
        svc = self._make_catalog_svc(mem_repo)
        detail = svc.get_published_lab_detail(lab_id=draft.lab_id, actor_user="learner1")
        assert detail is not None
        fields = set(detail.model_fields.keys())
        assert "raw_article_text" not in fields
        assert "article_text" not in fields
        assert "source_text" not in fields


# ---------------------------------------------------------------------------
# D. Regression tests
# ---------------------------------------------------------------------------


class TestRegression:
    def test_existing_labs_remain_visible_via_catalog(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo, publish_status=PublishStatus.DRAFT)
        r = admin_client.get(f"/api/labgen/drafts/{draft.lab_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["title"] == "K8s Basics"

    def test_patch_non_article_fields_unaffected(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo)
        r = admin_client.patch(
            f"/api/labgen/drafts/{draft.lab_id}",
            json={"title": "Updated Title"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["title"] == "Updated Title"
        assert data["article_url"] is None

    def test_k8s_lab_step_structure_unchanged(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo)
        admin_client.patch(
            f"/api/labgen/drafts/{draft.lab_id}",
            json={"article_url": "https://example.com/k8s"},
        )
        r = admin_client.get(f"/api/labgen/drafts/{draft.lab_id}")
        assert r.status_code == 200
        steps = r.json()["steps"]
        assert len(steps) == 1
        assert steps[0]["step_id"] == "s1"

    def test_no_llm_calls_triggered(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo)
        r = admin_client.patch(
            f"/api/labgen/drafts/{draft.lab_id}",
            json={"article_url": "https://example.com", "cta_enabled": True},
        )
        assert r.status_code == 200

    def test_cta_endpoint_does_not_modify_draft(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo, article_url="https://example.com")
        admin_client.get(f"/api/labgen/drafts/{draft.lab_id}/cta")
        saved = mem_repo.get(draft.lab_id)
        assert saved.article_url == "https://example.com"

    def test_publish_status_not_changed_by_article_patch(self, admin_client, mem_repo):
        draft = _make_draft(mem_repo, publish_status=PublishStatus.DRAFT)
        admin_client.patch(
            f"/api/labgen/drafts/{draft.lab_id}",
            json={"article_url": "https://example.com", "cta_enabled": True},
        )
        saved = mem_repo.get(draft.lab_id)
        assert saved.publish_status == PublishStatus.DRAFT
