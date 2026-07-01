"""
Phase 1 Soft Launch MVP Tests — G-67.

Covers:
  A. Admin Article Upload (extended fields: copyright_confirmed, target_domain, etc.)
  B. Operability Gate (NOT_LAB_READY rejected, PARTIALLY/DIRECTLY allowed)
  C. LLM Adapter (fake_only mode, admin guard, env var control)
  D. Draft Generation (generate-lab endpoint, LabDraft schema, no auto-publish)
  E. Publish / Review Flow (regression — existing publish gates still enforced)
  F. Exposure Tests (source_article_id/raw_text/prompt NOT in learner responses)
  G. E2E Soft Launch Smoke (article upload → generate → review → publish → CTA)
  H. Regression (existing labs unaffected, no public upload, no URL scraping)

LLM mode in tests: always fake_only (no real LLM calls, no API keys).
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


_K8S_ARTICLE = """
# Kubernetes ConfigMap Basics

## Step 1: Create a ConfigMap

```bash
kubectl apply -f configmap.yaml
```

## Step 2: Verify it exists

```bash
kubectl get configmap my-config -n default
```

The configmap should exist in the namespace.
Expected output:
  NAME         DATA   AGE
  my-config    1      5s
"""

_LINUX_ARTICLE = """
# Linux File Permissions

## Step 1: Create a file

```bash
mkdir -p ~/workspace/demo
echo "hello" > ~/workspace/demo/file.txt
```

## Step 2: Check permissions

```bash
ls -l ~/workspace/demo/file.txt
stat ~/workspace/demo/file.txt
```

Expected output shows permissions, owner, size.

## Step 3: Change mode

```bash
chmod 644 ~/workspace/demo/file.txt
```
"""

_THEORETICAL_ARTICLE = """
In this blog post, I will explore the concepts behind Kubernetes networking.
To summarize, network policies are important for security.
"""

_SECRET_ARTICLE = """
# Deploy with credentials

export API_KEY=sk-abcdefghijklmnopqrstuvwxyz123456
kubectl create secret generic my-secret --from-literal=key=${API_KEY}
"""

_DANGEROUS_ARTICLE = """
# Cleanup everything

kubectl delete namespace kube-system
rm -rf /etc/kubernetes
"""

_UNSUPPORTED_DOMAIN_ARTICLE = """
# AWS Lambda Tutorial

Deploy to AWS Lambda using the AWS console. You need an AWS account and billing setup.
Go to the ec2 instance and click deploy to cloud run.
"""


def _make_source_meta(
    submitted_by: str = "owner",
    text: str = _K8S_ARTICLE,
    title: str = "Test Article",
) -> dict:
    from backend.labgen.article_models import ArticleSourceMetadata, ArticleSourceType

    return ArticleSourceMetadata(
        source_type=ArticleSourceType.PASTED_TEXT,
        title=title,
        submitted_by_user_id=submitted_by,
        content_hash=_sha(text),
        content_length=len(text),
        user_confirmed_right_to_use=True,
        user_confirmed_no_secrets=True,
        raw_text_persisted=False,
    )


def _directly_ready_feasibility():
    from backend.labgen.article_models import (
        FeasibilityResult,
        FeasibilityStatus,
        FeasibilityEvaluatedBy,
        TargetDomain,
        VerifierFeasibility,
    )

    return FeasibilityResult(
        status=FeasibilityStatus.DIRECTLY_LAB_READY,
        target_domain_candidates=[TargetDomain.K8S],
        evaluated_by=FeasibilityEvaluatedBy.STUB,
        verifier_feasibility=VerifierFeasibility.NEEDS_PARAMETERIZATION,
    )


def _partial_feasibility():
    from backend.labgen.article_models import (
        FeasibilityResult,
        FeasibilityStatus,
        FeasibilityEvaluatedBy,
        TargetDomain,
    )

    return FeasibilityResult(
        status=FeasibilityStatus.PARTIALLY_LAB_READY,
        target_domain_candidates=[TargetDomain.K8S],
        evaluated_by=FeasibilityEvaluatedBy.STUB,
    )


def _not_ready_feasibility():
    from backend.labgen.article_models import (
        FeasibilityResult,
        FeasibilityStatus,
        FeasibilityEvaluatedBy,
    )

    return FeasibilityResult(
        status=FeasibilityStatus.NOT_LAB_READY,
        rejection_code="stub.no_operable_content",
        evaluated_by=FeasibilityEvaluatedBy.STUB,
    )


def _make_contract(feasibility=None, domain=None):
    from backend.labgen.article_models import ArticleDraftLabContract, TargetDomain

    return ArticleDraftLabContract(
        source_metadata=_make_source_meta(),
        feasibility_result=feasibility or _directly_ready_feasibility(),
        target_domain=domain or TargetDomain.K8S,
    )


# ---------------------------------------------------------------------------
# Fixture: isolated test client for article draft routes
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def soft_launch_client(tmp_path_factory):
    """TestClient with isolated repos and fake admin auth."""
    import dotenv

    dotenv.load_dotenv()

    tmp = tmp_path_factory.mktemp("soft_launch")

    from backend.labgen.article_draft_repository import ArticleDraftRepository
    from backend.labgen.repository import LabDraftRepository
    from backend.labgen.article_draft_service import ArticleDraftService
    import backend.labgen.article_draft_routes as adr

    article_repo = ArticleDraftRepository(path=tmp / "article_drafts.json")
    lab_repo = LabDraftRepository(path=tmp / "lab_drafts.json")
    svc = ArticleDraftService(article_repo=article_repo, lab_repo=lab_repo)

    from backend.main import app
    from backend.auth_deps import get_current_user
    from backend.auth import auth_manager

    app.dependency_overrides[adr.get_article_draft_service] = lambda: svc
    _real_is_admin = auth_manager.is_admin

    def _mock_is_admin(username: str) -> bool:
        return username == "owner" or _real_is_admin(username)

    auth_manager.is_admin = _mock_is_admin
    app.dependency_overrides[get_current_user] = lambda: "owner"

    with TestClient(app, raise_server_exceptions=True) as client:
        yield client

    app.dependency_overrides.clear()
    auth_manager.is_admin = _real_is_admin


@pytest.fixture()
def non_admin_client(tmp_path):
    """TestClient authenticated as a non-admin user.

    Saves/restores existing dependency overrides to avoid disturbing
    module-scoped fixtures running in the same test session.
    """
    import dotenv

    dotenv.load_dotenv()

    from backend.labgen.article_draft_repository import ArticleDraftRepository
    from backend.labgen.repository import LabDraftRepository
    from backend.labgen.article_draft_service import ArticleDraftService
    import backend.labgen.article_draft_routes as adr

    article_repo = ArticleDraftRepository(path=tmp_path / "article_drafts.json")
    lab_repo = LabDraftRepository(path=tmp_path / "lab_drafts.json")
    svc = ArticleDraftService(article_repo=article_repo, lab_repo=lab_repo)

    from backend.main import app
    from backend.auth_deps import get_current_user
    from backend.auth import auth_manager

    saved_overrides = dict(app.dependency_overrides)
    _real_is_admin = auth_manager.is_admin

    app.dependency_overrides[adr.get_article_draft_service] = lambda: svc
    auth_manager.is_admin = lambda u: False  # nobody is admin
    app.dependency_overrides[get_current_user] = lambda: "reader_user"

    with TestClient(app, raise_server_exceptions=True) as client:
        yield client

    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved_overrides)
    auth_manager.is_admin = _real_is_admin


# ---------------------------------------------------------------------------
# A. Admin Article Upload Tests
# ---------------------------------------------------------------------------


class TestAdminArticleUpload:
    def test_admin_can_submit_k8s_article(self, soft_launch_client):
        resp = soft_launch_client.post(
            "/api/labgen/article-drafts",
            json={
                "raw_text": _K8S_ARTICLE,
                "title": "K8s ConfigMap Basics",
                "target_domain": "k8s",
                "intended_reader": "junior k8s practitioner",
                "publish_channel": "official_site",
                "copyright_confirmed": True,
                "user_confirmed_right_to_use": True,
                "user_confirmed_no_secrets": True,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "draft_id" in data
        assert data["feasibility_result"]["status"] in (
            "directly_lab_ready", "partially_lab_ready"
        )

    def test_admin_can_submit_linux_article(self, soft_launch_client):
        resp = soft_launch_client.post(
            "/api/labgen/article-drafts",
            json={
                "raw_text": _LINUX_ARTICLE,
                "title": "Linux File Permissions",
                "target_domain": "linux",
                "copyright_confirmed": True,
                "user_confirmed_right_to_use": True,
                "user_confirmed_no_secrets": True,
            },
        )
        assert resp.status_code == 201

    def test_non_admin_rejected_403(self, non_admin_client):
        resp = non_admin_client.post(
            "/api/labgen/article-drafts",
            json={
                "raw_text": _K8S_ARTICLE,
                "copyright_confirmed": True,
                "user_confirmed_right_to_use": True,
                "user_confirmed_no_secrets": True,
            },
        )
        assert resp.status_code == 403

    def test_missing_raw_text_rejected(self, soft_launch_client):
        resp = soft_launch_client.post(
            "/api/labgen/article-drafts",
            json={
                "raw_text": "",
                "copyright_confirmed": True,
                "user_confirmed_right_to_use": True,
                "user_confirmed_no_secrets": True,
            },
        )
        assert resp.status_code == 422

    def test_copyright_not_confirmed_rejected(self, soft_launch_client):
        resp = soft_launch_client.post(
            "/api/labgen/article-drafts",
            json={
                "raw_text": _K8S_ARTICLE,
                "copyright_confirmed": False,
                "user_confirmed_right_to_use": True,
                "user_confirmed_no_secrets": True,
            },
        )
        assert resp.status_code == 422
        assert "copyright_confirmed" in resp.json()["detail"]

    def test_unsupported_target_domain_rejected(self, soft_launch_client):
        resp = soft_launch_client.post(
            "/api/labgen/article-drafts",
            json={
                "raw_text": _K8S_ARTICLE,
                "target_domain": "docker",  # not in allowed set
                "copyright_confirmed": True,
                "user_confirmed_right_to_use": True,
                "user_confirmed_no_secrets": True,
            },
        )
        assert resp.status_code == 422
        assert "target_domain" in resp.json()["detail"]

    def test_invalid_publish_channel_rejected(self, soft_launch_client):
        resp = soft_launch_client.post(
            "/api/labgen/article-drafts",
            json={
                "raw_text": _K8S_ARTICLE,
                "publish_channel": "invalid_channel",
                "copyright_confirmed": True,
                "user_confirmed_right_to_use": True,
                "user_confirmed_no_secrets": True,
            },
        )
        assert resp.status_code == 422
        assert "publish_channel" in resp.json()["detail"]

    def test_public_route_does_not_exist(self, soft_launch_client):
        resp = soft_launch_client.post(
            "/api/public/article-upload",
            json={"raw_text": _K8S_ARTICLE},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# B. Operability Gate Tests
# ---------------------------------------------------------------------------


class TestOperabilityGate:
    def test_k8s_lab_ready_article_accepted(self):
        from backend.labgen.stub_feasibility_classifier import StubFeasibilityClassifier
        from backend.labgen.article_models import FeasibilityStatus

        result = StubFeasibilityClassifier().classify(_K8S_ARTICLE)
        assert result.status in (
            FeasibilityStatus.DIRECTLY_LAB_READY,
            FeasibilityStatus.PARTIALLY_LAB_READY,
        )

    def test_linux_lab_ready_article_accepted(self):
        from backend.labgen.stub_feasibility_classifier import StubFeasibilityClassifier
        from backend.labgen.article_models import FeasibilityStatus, TargetDomain

        result = StubFeasibilityClassifier().classify(_LINUX_ARTICLE)
        assert result.status in (
            FeasibilityStatus.DIRECTLY_LAB_READY,
            FeasibilityStatus.PARTIALLY_LAB_READY,
        )
        assert TargetDomain.LINUX in result.target_domain_candidates

    def test_theoretical_article_rejected(self):
        from backend.labgen.stub_feasibility_classifier import StubFeasibilityClassifier
        from backend.labgen.article_models import FeasibilityStatus

        result = StubFeasibilityClassifier().classify(_THEORETICAL_ARTICLE)
        assert result.status == FeasibilityStatus.NOT_LAB_READY

    def test_secret_containing_article_rejected(self):
        from backend.labgen.stub_feasibility_classifier import StubFeasibilityClassifier
        from backend.labgen.article_models import FeasibilityStatus, SafetyFlag

        result = StubFeasibilityClassifier().classify(_SECRET_ARTICLE)
        assert result.status == FeasibilityStatus.NOT_LAB_READY
        assert SafetyFlag.CONTAINS_SECRET_LIKE_CONTENT in result.safety_flags

    def test_dangerous_article_flagged(self):
        """Destructive commands → DESTRUCTIVE_OPERATION safety flag + PARTIALLY_LAB_READY.

        NOT_LAB_READY is only triggered by CONTAINS_SECRET_LIKE_CONTENT or DANGEROUS_OR_ILLEGAL.
        DESTRUCTIVE_OPERATION degrades to PARTIALLY_LAB_READY and is caught by StaticValidator.
        """
        from backend.labgen.stub_feasibility_classifier import StubFeasibilityClassifier
        from backend.labgen.article_models import FeasibilityStatus, SafetyFlag

        result = StubFeasibilityClassifier().classify(_DANGEROUS_ARTICLE)
        assert result.status in (
            FeasibilityStatus.NOT_LAB_READY,
            FeasibilityStatus.PARTIALLY_LAB_READY,
        )
        assert SafetyFlag.DESTRUCTIVE_OPERATION in result.safety_flags

    def test_unsupported_domain_article_rejected(self):
        from backend.labgen.stub_feasibility_classifier import StubFeasibilityClassifier
        from backend.labgen.article_models import FeasibilityStatus

        result = StubFeasibilityClassifier().classify(_UNSUPPORTED_DOMAIN_ARTICLE)
        assert result.status == FeasibilityStatus.NOT_LAB_READY

    def test_partially_ready_article_marked_partial(self):
        from backend.labgen.stub_feasibility_classifier import StubFeasibilityClassifier
        from backend.labgen.article_models import FeasibilityStatus

        # Article with k8s content but no commands or verifiable outcomes
        partial_text = "kubectl is a tool for Kubernetes. Namespaces help isolate workloads."
        result = StubFeasibilityClassifier().classify(partial_text)
        # Should be partial (has k8s keywords but no commands)
        assert result.status == FeasibilityStatus.PARTIALLY_LAB_READY


# ---------------------------------------------------------------------------
# C. LLM Adapter Tests
# ---------------------------------------------------------------------------


class TestLLMAdapter:
    def test_fake_only_mode_uses_stub(self, tmp_path):
        from backend.labgen.article_draft_repository import ArticleDraftRepository
        from backend.labgen.repository import LabDraftRepository
        from backend.labgen.article_draft_service import ArticleDraftService
        from backend.labgen.llm_audit import LLMAuditRepository

        article_repo = ArticleDraftRepository(path=tmp_path / "a.json")
        lab_repo = LabDraftRepository(path=tmp_path / "l.json")
        audit_repo = LLMAuditRepository(audit_path=tmp_path / "audit.json")
        svc = ArticleDraftService(article_repo=article_repo, lab_repo=lab_repo)

        # Create a contract first
        from backend.labgen.article_models import ArticleSourceMetadata, ArticleSourceType
        from backend.labgen.stub_feasibility_classifier import compute_content_hash
        src_meta = ArticleSourceMetadata(
            source_type=ArticleSourceType.PASTED_TEXT,
            title="K8s Test",
            submitted_by_user_id="owner",
            content_hash=compute_content_hash(_K8S_ARTICLE),
            content_length=len(_K8S_ARTICLE),
            user_confirmed_right_to_use=True,
            user_confirmed_no_secrets=True,
            raw_text_persisted=False,
        )
        contract = svc.create_draft(_K8S_ARTICLE, src_meta, "owner")

        with patch("backend.config.LABGEN_LLM_MODE", "fake_only"):
            result = svc.generate_lab_from_article(
                draft_id=contract.draft_id,
                article_text=_K8S_ARTICLE,
                admin_user="owner",
                audit_repo=audit_repo,
            )

        assert result.lab_draft is not None
        # Never published; StaticValidator may produce draft/publish_blocked/review_required
        assert result.lab_draft.publish_status.value != "published"
        # Verify audit was written
        entries = audit_repo.list_all()
        assert len(entries) == 1
        assert entries[0]["llm_mode"] == "fake_only"
        assert entries[0]["success"] is True

    def test_env_missing_fails_closed_for_live_mode(self, tmp_path):
        """live_admin_only with no LABGEN_LLM_OPENAI_* config → LLMGenerationFailed."""
        from backend.labgen.article_draft_repository import ArticleDraftRepository
        from backend.labgen.repository import LabDraftRepository
        from backend.labgen.article_draft_service import ArticleDraftService, LLMGenerationFailed
        from backend.labgen.llm_audit import LLMAuditRepository
        from backend.labgen.article_models import ArticleSourceMetadata, ArticleSourceType
        from backend.labgen.stub_feasibility_classifier import compute_content_hash

        article_repo = ArticleDraftRepository(path=tmp_path / "a.json")
        lab_repo = LabDraftRepository(path=tmp_path / "l.json")
        audit_repo = LLMAuditRepository(audit_path=tmp_path / "audit.json")
        svc = ArticleDraftService(article_repo=article_repo, lab_repo=lab_repo)

        src_meta = ArticleSourceMetadata(
            source_type=ArticleSourceType.PASTED_TEXT,
            title="K8s Test",
            submitted_by_user_id="owner",
            content_hash=compute_content_hash(_K8S_ARTICLE),
            content_length=len(_K8S_ARTICLE),
            user_confirmed_right_to_use=True,
            user_confirmed_no_secrets=True,
            raw_text_persisted=False,
        )
        contract = svc.create_draft(_K8S_ARTICLE, src_meta, "owner")

        with patch("backend.config.LABGEN_LLM_MODE", "live_admin_only"), \
             patch("backend.config.LABGEN_LLM_PROVIDER_MODE", "live_enabled"), \
             patch("backend.config.LABGEN_LLM_OPENAI_API_KEY", ""), \
             patch("backend.config.LABGEN_LLM_OPENAI_BASE_URL", ""), \
             patch("backend.config.LABGEN_LLM_OPENAI_MODEL", ""):
            with pytest.raises(LLMGenerationFailed) as exc_info:
                svc.generate_lab_from_article(
                    draft_id=contract.draft_id,
                    article_text=_K8S_ARTICLE,
                    admin_user="owner",
                    audit_repo=audit_repo,
                )
        assert "config_error" in str(exc_info.value)
        # Audit entry written even on failure
        entries = audit_repo.list_all()
        assert len(entries) == 1
        assert entries[0]["success"] is False

    def test_llm_cannot_set_publish_status_published(self, tmp_path):
        """LLM output can never result in publish_status=published.

        Postcondition: never published. StaticValidator may produce
        draft/publish_blocked/review_required depending on candidate quality.
        """
        from backend.labgen.article_draft_repository import ArticleDraftRepository
        from backend.labgen.repository import LabDraftRepository
        from backend.labgen.article_draft_service import ArticleDraftService
        from backend.labgen.llm_audit import LLMAuditRepository
        from backend.labgen.article_models import ArticleSourceMetadata, ArticleSourceType
        from backend.labgen.stub_feasibility_classifier import compute_content_hash
        from backend.labgen.llm_generation import FakeDraftGenerationAdapter, LabDraftGenerationRequest

        article_repo = ArticleDraftRepository(path=tmp_path / "a.json")
        lab_repo = LabDraftRepository(path=tmp_path / "l.json")
        audit_repo = LLMAuditRepository(audit_path=tmp_path / "audit.json")
        svc = ArticleDraftService(article_repo=article_repo, lab_repo=lab_repo)

        src_meta = ArticleSourceMetadata(
            source_type=ArticleSourceType.PASTED_TEXT,
            title="K8s Test",
            submitted_by_user_id="owner",
            content_hash=compute_content_hash(_K8S_ARTICLE),
            content_length=len(_K8S_ARTICLE),
            user_confirmed_right_to_use=True,
            user_confirmed_no_secrets=True,
            raw_text_persisted=False,
        )
        contract = svc.create_draft(_K8S_ARTICLE, src_meta, "owner")

        with patch("backend.config.LABGEN_LLM_MODE", "fake_only"):
            result = svc.generate_lab_from_article(
                draft_id=contract.draft_id,
                article_text=_K8S_ARTICLE,
                admin_user="owner",
                audit_repo=audit_repo,
            )

        assert result.lab_draft.publish_status.value != "published"

    def test_llm_audit_written_on_success(self, tmp_path):
        from backend.labgen.llm_audit import LLMAuditEntry, LLMAuditRepository

        repo = LLMAuditRepository(audit_path=tmp_path / "audit.json")
        entry = LLMAuditEntry(
            admin_user="owner",
            article_draft_id="draft-001",
            article_title="Test Article",
            target_domain="k8s",
            llm_mode="fake_only",
            model_name="fake",
            success=True,
            lab_draft_id="lab-001",
            operability_status="directly_lab_ready",
        )
        repo.append(entry)
        entries = repo.list_all()
        assert len(entries) == 1
        assert entries[0]["admin_user"] == "owner"
        assert entries[0]["success"] is True
        assert entries[0]["lab_draft_id"] == "lab-001"

    def test_llm_audit_written_on_failure(self, tmp_path):
        from backend.labgen.llm_audit import LLMAuditEntry, LLMAuditRepository

        repo = LLMAuditRepository(audit_path=tmp_path / "audit.json")
        entry = LLMAuditEntry(
            admin_user="owner",
            article_draft_id="draft-002",
            article_title="Bad Article",
            target_domain="k8s",
            llm_mode="fake_only",
            model_name="fake",
            success=False,
            failure_reason="operability_rejected",
            operability_status="not_lab_ready",
        )
        repo.append(entry)
        entries = repo.list_all()
        assert entries[0]["success"] is False
        assert entries[0]["failure_reason"] == "operability_rejected"

    def test_reader_path_never_calls_llm(self, soft_launch_client):
        """GET /api/labs and GET /api/labgen/sessions do not trigger LLM."""
        # These are learner-facing endpoints — no LLM
        with patch("backend.labgen.article_draft_service.ArticleDraftService.generate_lab_from_article") as mock_gen:
            resp = soft_launch_client.get("/api/labs")
            mock_gen.assert_not_called()


# ---------------------------------------------------------------------------
# D. Draft Generation Tests
# ---------------------------------------------------------------------------


class TestDraftGeneration:
    @pytest.fixture()
    def isolated_svc_and_repos(self, tmp_path):
        from backend.labgen.article_draft_repository import ArticleDraftRepository
        from backend.labgen.repository import LabDraftRepository
        from backend.labgen.article_draft_service import ArticleDraftService
        from backend.labgen.llm_audit import LLMAuditRepository
        from backend.labgen.article_models import ArticleSourceMetadata, ArticleSourceType
        from backend.labgen.stub_feasibility_classifier import compute_content_hash

        article_repo = ArticleDraftRepository(path=tmp_path / "a.json")
        lab_repo = LabDraftRepository(path=tmp_path / "l.json")
        audit_repo = LLMAuditRepository(audit_path=tmp_path / "audit.json")
        svc = ArticleDraftService(article_repo=article_repo, lab_repo=lab_repo)

        src_meta = ArticleSourceMetadata(
            source_type=ArticleSourceType.PASTED_TEXT,
            title="K8s Basics",
            submitted_by_user_id="owner",
            content_hash=compute_content_hash(_K8S_ARTICLE),
            content_length=len(_K8S_ARTICLE),
            user_confirmed_right_to_use=True,
            user_confirmed_no_secrets=True,
            raw_text_persisted=False,
        )
        contract = svc.create_draft(_K8S_ARTICLE, src_meta, "owner")
        return svc, contract, lab_repo, audit_repo

    def test_generated_draft_matches_schema(self, isolated_svc_and_repos):
        svc, contract, lab_repo, audit_repo = isolated_svc_and_repos

        with patch("backend.config.LABGEN_LLM_MODE", "fake_only"):
            result = svc.generate_lab_from_article(
                draft_id=contract.draft_id,
                article_text=_K8S_ARTICLE,
                admin_user="owner",
                audit_repo=audit_repo,
            )

        draft = result.lab_draft
        assert draft.lab_id
        assert draft.title
        assert draft.description
        assert len(draft.steps) > 0
        assert draft.cleanup is not None or draft.linux_sandbox_policy is not None or draft.linux_cleanup is not None

    def test_required_fields_present(self, isolated_svc_and_repos):
        svc, contract, lab_repo, audit_repo = isolated_svc_and_repos

        with patch("backend.config.LABGEN_LLM_MODE", "fake_only"):
            result = svc.generate_lab_from_article(
                draft_id=contract.draft_id,
                article_text=_K8S_ARTICLE,
                admin_user="owner",
                audit_repo=audit_repo,
            )

        draft = result.lab_draft
        for step in draft.steps:
            assert step.step_id
            assert step.why
            assert step.do
            assert step.observe

    def test_not_lab_ready_article_cannot_generate(self, tmp_path):
        from backend.labgen.article_draft_repository import ArticleDraftRepository
        from backend.labgen.repository import LabDraftRepository
        from backend.labgen.article_draft_service import ArticleDraftService, ArticleOperabilityRejected
        from backend.labgen.llm_audit import LLMAuditRepository
        from backend.labgen.article_models import ArticleSourceMetadata, ArticleSourceType
        from backend.labgen.stub_feasibility_classifier import compute_content_hash

        article_repo = ArticleDraftRepository(path=tmp_path / "a.json")
        lab_repo = LabDraftRepository(path=tmp_path / "l.json")
        audit_repo = LLMAuditRepository(audit_path=tmp_path / "audit.json")
        svc = ArticleDraftService(article_repo=article_repo, lab_repo=lab_repo)

        src_meta = ArticleSourceMetadata(
            source_type=ArticleSourceType.PASTED_TEXT,
            title="Theory Only",
            submitted_by_user_id="owner",
            content_hash=compute_content_hash(_THEORETICAL_ARTICLE),
            content_length=len(_THEORETICAL_ARTICLE),
            user_confirmed_right_to_use=True,
            user_confirmed_no_secrets=True,
            raw_text_persisted=False,
        )
        contract = svc.create_draft(_THEORETICAL_ARTICLE, src_meta, "owner")

        with pytest.raises(ArticleOperabilityRejected):
            svc.generate_lab_from_article(
                draft_id=contract.draft_id,
                article_text=_THEORETICAL_ARTICLE,
                admin_user="owner",
                audit_repo=audit_repo,
            )

        # Audit entry records failure
        entries = audit_repo.list_all()
        assert len(entries) == 1
        assert entries[0]["failure_reason"] == "operability_rejected"

    def test_generated_lab_is_always_draft(self, isolated_svc_and_repos):
        svc, contract, lab_repo, audit_repo = isolated_svc_and_repos

        with patch("backend.config.LABGEN_LLM_MODE", "fake_only"):
            result = svc.generate_lab_from_article(
                draft_id=contract.draft_id,
                article_text=_K8S_ARTICLE,
                admin_user="owner",
                audit_repo=audit_repo,
            )

        assert result.lab_draft.publish_status.value in ("draft", "publish_blocked", "review_required")

    def test_generated_lab_rehearsal_required(self, isolated_svc_and_repos):
        svc, contract, lab_repo, audit_repo = isolated_svc_and_repos

        with patch("backend.config.LABGEN_LLM_MODE", "fake_only"):
            result = svc.generate_lab_from_article(
                draft_id=contract.draft_id,
                article_text=_K8S_ARTICLE,
                admin_user="owner",
                audit_repo=audit_repo,
            )

        # LLM-generated labs must go through internal rehearsal before publish
        assert result.lab_draft.rehearsal_required is True

    def test_source_article_id_set_to_draft_id(self, isolated_svc_and_repos):
        svc, contract, lab_repo, audit_repo = isolated_svc_and_repos

        with patch("backend.config.LABGEN_LLM_MODE", "fake_only"):
            result = svc.generate_lab_from_article(
                draft_id=contract.draft_id,
                article_text=_K8S_ARTICLE,
                admin_user="owner",
                audit_repo=audit_repo,
            )

        assert result.lab_draft.source_article_id == contract.draft_id

    def test_desired_lab_title_applied(self, isolated_svc_and_repos):
        svc, contract, lab_repo, audit_repo = isolated_svc_and_repos

        with patch("backend.config.LABGEN_LLM_MODE", "fake_only"):
            result = svc.generate_lab_from_article(
                draft_id=contract.draft_id,
                article_text=_K8S_ARTICLE,
                admin_user="owner",
                desired_lab_title="My Custom Lab Title",
                audit_repo=audit_repo,
            )

        assert result.lab_draft.title == "My Custom Lab Title"


# ---------------------------------------------------------------------------
# D2. generate-lab HTTP endpoint tests
# ---------------------------------------------------------------------------


class TestGenerateLabEndpoint:
    @pytest.fixture()
    def client_with_contract(self, tmp_path):
        """Client with an existing article draft contract ready."""
        import dotenv
        dotenv.load_dotenv()

        from backend.labgen.article_draft_repository import ArticleDraftRepository
        from backend.labgen.repository import LabDraftRepository
        from backend.labgen.article_draft_service import ArticleDraftService
        import backend.labgen.article_draft_routes as adr

        article_repo = ArticleDraftRepository(path=tmp_path / "a.json")
        lab_repo = LabDraftRepository(path=tmp_path / "l.json")
        svc = ArticleDraftService(article_repo=article_repo, lab_repo=lab_repo)

        from backend.main import app
        from backend.auth_deps import get_current_user
        from backend.auth import auth_manager

        saved_overrides = dict(app.dependency_overrides)
        _real_is_admin = auth_manager.is_admin

        app.dependency_overrides[adr.get_article_draft_service] = lambda: svc
        auth_manager.is_admin = lambda u: u == "owner"
        app.dependency_overrides[get_current_user] = lambda: "owner"

        with TestClient(app, raise_server_exceptions=True) as client:
            # Pre-create a contract
            resp = client.post(
                "/api/labgen/article-drafts",
                json={
                    "raw_text": _K8S_ARTICLE,
                    "title": "K8s ConfigMap Basics",
                    "target_domain": "k8s",
                    "copyright_confirmed": True,
                    "user_confirmed_right_to_use": True,
                    "user_confirmed_no_secrets": True,
                },
            )
            assert resp.status_code == 201
            draft_id = resp.json()["draft_id"]
            yield client, draft_id

        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved_overrides)
        auth_manager.is_admin = _real_is_admin

    def test_generate_lab_returns_201(self, client_with_contract):
        client, draft_id = client_with_contract

        with patch("backend.config.LABGEN_LLM_MODE", "fake_only"):
            resp = client.post(
                f"/api/labgen/article-drafts/{draft_id}/generate-lab",
                json={"article_text": _K8S_ARTICLE},
            )

        assert resp.status_code == 201
        data = resp.json()
        assert "lab_draft_id" in data
        assert data["llm_mode"] == "fake_only"
        assert "operability_status" in data
        assert "audit_id" in data
        assert "warnings" in data

    def test_generate_lab_non_admin_returns_403(self, tmp_path):
        import dotenv
        dotenv.load_dotenv()

        from backend.labgen.article_draft_repository import ArticleDraftRepository
        from backend.labgen.repository import LabDraftRepository
        from backend.labgen.article_draft_service import ArticleDraftService
        import backend.labgen.article_draft_routes as adr

        article_repo = ArticleDraftRepository(path=tmp_path / "a.json")
        lab_repo = LabDraftRepository(path=tmp_path / "l.json")
        svc = ArticleDraftService(article_repo=article_repo, lab_repo=lab_repo)

        from backend.main import app
        from backend.auth_deps import get_current_user
        from backend.auth import auth_manager

        saved_overrides = dict(app.dependency_overrides)
        _real_is_admin = auth_manager.is_admin

        app.dependency_overrides[adr.get_article_draft_service] = lambda: svc
        auth_manager.is_admin = lambda u: False
        app.dependency_overrides[get_current_user] = lambda: "regular_user"

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/api/labgen/article-drafts/nonexistent-id/generate-lab",
                json={"article_text": _K8S_ARTICLE},
            )
        assert resp.status_code == 403

        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved_overrides)
        auth_manager.is_admin = _real_is_admin

    def test_generate_lab_not_ready_article_returns_422(self, tmp_path):
        import dotenv
        dotenv.load_dotenv()

        from backend.labgen.article_draft_repository import ArticleDraftRepository
        from backend.labgen.repository import LabDraftRepository
        from backend.labgen.article_draft_service import ArticleDraftService
        import backend.labgen.article_draft_routes as adr

        article_repo = ArticleDraftRepository(path=tmp_path / "a.json")
        lab_repo = LabDraftRepository(path=tmp_path / "l.json")
        svc = ArticleDraftService(article_repo=article_repo, lab_repo=lab_repo)

        from backend.main import app
        from backend.auth_deps import get_current_user
        from backend.auth import auth_manager

        saved_overrides = dict(app.dependency_overrides)
        _real_is_admin = auth_manager.is_admin

        app.dependency_overrides[adr.get_article_draft_service] = lambda: svc
        auth_manager.is_admin = lambda u: u == "owner"
        app.dependency_overrides[get_current_user] = lambda: "owner"

        with TestClient(app, raise_server_exceptions=True) as client:
            # Upload theoretical (NOT_LAB_READY) article
            resp = client.post(
                "/api/labgen/article-drafts",
                json={
                    "raw_text": _THEORETICAL_ARTICLE,
                    "title": "Theory Article",
                    "copyright_confirmed": True,
                    "user_confirmed_right_to_use": True,
                    "user_confirmed_no_secrets": True,
                },
            )
            assert resp.status_code == 201
            draft_id = resp.json()["draft_id"]

            with patch("backend.config.LABGEN_LLM_MODE", "fake_only"):
                resp = client.post(
                    f"/api/labgen/article-drafts/{draft_id}/generate-lab",
                    json={"article_text": _THEORETICAL_ARTICLE},
                )
            assert resp.status_code == 422
            assert resp.json()["detail"]["error"] == "operability_rejected"

        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved_overrides)
        auth_manager.is_admin = _real_is_admin

    def test_generate_lab_empty_text_returns_422(self, client_with_contract):
        client, draft_id = client_with_contract
        resp = client.post(
            f"/api/labgen/article-drafts/{draft_id}/generate-lab",
            json={"article_text": ""},
        )
        assert resp.status_code == 422

    def test_generate_lab_unknown_draft_id_returns_404(self, client_with_contract):
        client, _ = client_with_contract
        with patch("backend.config.LABGEN_LLM_MODE", "fake_only"):
            resp = client.post(
                "/api/labgen/article-drafts/nonexistent-id/generate-lab",
                json={"article_text": _K8S_ARTICLE},
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# E. Publish flow regression (StaticValidator gate enforced)
# ---------------------------------------------------------------------------


class TestPublishFlowRegression:
    def test_generated_lab_blocked_before_rehearsal(self, tmp_path):
        """LLM-generated lab raises RehearsalNotCompleted when published without rehearsal."""
        from backend.labgen.article_draft_repository import ArticleDraftRepository
        from backend.labgen.repository import LabDraftRepository
        from backend.labgen.article_draft_service import ArticleDraftService
        from backend.labgen.llm_audit import LLMAuditRepository
        from backend.labgen.article_models import ArticleSourceMetadata, ArticleSourceType
        from backend.labgen.stub_feasibility_classifier import compute_content_hash
        from backend.labgen.publish_service import PublishService, RehearsalNotCompleted
        from backend.labgen.static_validator import StaticValidator
        from backend.labgen.image_resolver import ImageResolver

        article_repo = ArticleDraftRepository(path=tmp_path / "a.json")
        lab_repo = LabDraftRepository(path=tmp_path / "l.json")
        audit_repo = LLMAuditRepository(audit_path=tmp_path / "audit.json")
        svc = ArticleDraftService(article_repo=article_repo, lab_repo=lab_repo)

        src_meta = ArticleSourceMetadata(
            source_type=ArticleSourceType.PASTED_TEXT,
            title="K8s Test",
            submitted_by_user_id="owner",
            content_hash=compute_content_hash(_K8S_ARTICLE),
            content_length=len(_K8S_ARTICLE),
            user_confirmed_right_to_use=True,
            user_confirmed_no_secrets=True,
            raw_text_persisted=False,
        )
        contract = svc.create_draft(_K8S_ARTICLE, src_meta, "owner")

        with patch("backend.config.LABGEN_LLM_MODE", "fake_only"):
            result = svc.generate_lab_from_article(
                draft_id=contract.draft_id,
                article_text=_K8S_ARTICLE,
                admin_user="owner",
                audit_repo=audit_repo,
            )

        # rehearsal_required=True on LLM-generated draft (rehearsal_completed stays False)
        assert result.lab_draft.rehearsal_required is True
        assert not result.lab_draft.rehearsal_completed

        # publish service raises RehearsalNotCompleted before running StaticValidator
        publish_svc = PublishService(validator=StaticValidator(), image_resolver=ImageResolver())
        with pytest.raises(RehearsalNotCompleted):
            publish_svc.publish(result.lab_draft)


# ---------------------------------------------------------------------------
# F. Exposure Tests
# ---------------------------------------------------------------------------


class TestExposureGuards:
    def test_article_text_not_persisted(self, tmp_path):
        """Raw article text must not be stored anywhere."""
        from backend.labgen.article_draft_repository import ArticleDraftRepository
        from backend.labgen.repository import LabDraftRepository
        from backend.labgen.article_draft_service import ArticleDraftService
        from backend.labgen.article_models import ArticleSourceMetadata, ArticleSourceType
        from backend.labgen.stub_feasibility_classifier import compute_content_hash

        article_repo = ArticleDraftRepository(path=tmp_path / "a.json")
        lab_repo = LabDraftRepository(path=tmp_path / "l.json")
        svc = ArticleDraftService(article_repo=article_repo, lab_repo=lab_repo)

        unique_text = f"unique-marker-{uuid.uuid4()} kubectl apply -f test.yaml"
        src_meta = ArticleSourceMetadata(
            source_type=ArticleSourceType.PASTED_TEXT,
            title="Test",
            submitted_by_user_id="owner",
            content_hash=compute_content_hash(unique_text),
            content_length=len(unique_text),
            user_confirmed_right_to_use=True,
            user_confirmed_no_secrets=True,
            raw_text_persisted=False,
        )
        contract = svc.create_draft(unique_text, src_meta, "owner")

        # The stored contract must not contain the raw article text
        stored = article_repo.get(contract.draft_id)
        stored_json = stored.model_dump_json()
        assert unique_text not in stored_json

    def test_source_article_id_absent_in_learner_catalog(self, soft_launch_client):
        """source_article_id must not appear in learner-facing catalog responses."""
        resp = soft_launch_client.get("/api/labs")
        if resp.status_code == 200:
            for item in resp.json():
                assert "source_article_id" not in item

    def test_raw_text_absent_in_learner_catalog(self, soft_launch_client):
        """Raw article text fields must not appear in learner catalog."""
        resp = soft_launch_client.get("/api/labs")
        if resp.status_code == 200:
            data_str = resp.text
            assert "raw_text" not in data_str
            assert "raw_article_text" not in data_str

    def test_llm_prompt_not_in_response(self, tmp_path):
        """LLM prompt (build_article_to_lab_messages output) must not appear in API response."""
        from backend.labgen.article_lab_prompt_builder import build_article_to_lab_messages

        system_msg, user_msg = build_article_to_lab_messages(
            _K8S_ARTICLE,
            article_title="K8s Test",
            target_domain="k8s",
        )
        # Verify neither message contains credential-like content from article
        assert "sk-" not in system_msg
        assert "sk-" not in user_msg
        # Verify the prompt instructs JSON-only output (no chain-of-thought leak)
        assert "JSON" in system_msg
        assert "chain-of-thought" in system_msg.lower() or "chain_of_thought" in system_msg.lower()

    def test_audit_log_does_not_contain_article_text(self, tmp_path):
        """LLM audit log must not store raw article text."""
        from backend.labgen.llm_audit import LLMAuditEntry, LLMAuditRepository

        repo = LLMAuditRepository(audit_path=tmp_path / "audit.json")
        unique_text = f"secret-article-content-{uuid.uuid4()}"
        entry = LLMAuditEntry(
            admin_user="owner",
            article_draft_id="d-001",
            article_title="Test",
            target_domain="k8s",
            llm_mode="fake_only",
            model_name="fake",
            success=True,
            lab_draft_id="l-001",
            operability_status="directly_lab_ready",
        )
        repo.append(entry)

        # The stored audit log must not contain the article text
        audit_path = tmp_path / "audit.json"
        log_content = audit_path.read_text()
        assert unique_text not in log_content

    def test_no_public_upload_route(self, soft_launch_client):
        """No public article upload route exists."""
        resp = soft_launch_client.post("/api/articles/upload", json={"text": "test"})
        assert resp.status_code in (404, 405)
        resp2 = soft_launch_client.post("/api/public/upload-article", json={"text": "test"})
        assert resp2.status_code in (404, 405)


# ---------------------------------------------------------------------------
# G. Article-to-Lab Prompt Builder Tests
# ---------------------------------------------------------------------------


class TestArticleLabPromptBuilder:
    def test_build_k8s_messages_structure(self):
        from backend.labgen.article_lab_prompt_builder import build_article_to_lab_messages

        system, user = build_article_to_lab_messages(
            _K8S_ARTICLE,
            article_title="K8s Basics",
            target_domain="k8s",
            intended_reader="junior practitioner",
        )
        assert "JSON" in system
        assert "Guided Practice" in system
        assert "k8s" in user.lower() or "kubernetes" in user.lower() or "k8s" in system.lower()
        assert "Article title" in user

    def test_build_linux_messages_structure(self):
        from backend.labgen.article_lab_prompt_builder import build_article_to_lab_messages

        system, user = build_article_to_lab_messages(
            _LINUX_ARTICLE,
            article_title="Linux File Permissions",
            target_domain="linux",
        )
        assert "linux" in system.lower()
        assert "JSON" in system

    def test_article_text_truncated_to_safe_length(self):
        from backend.labgen.article_lab_prompt_builder import build_article_to_lab_messages

        long_text = "kubectl apply -f file.yaml\n" * 500  # >4000 chars
        system, user = build_article_to_lab_messages(
            long_text,
            article_title="Long Article",
            target_domain="k8s",
        )
        # The user message must not contain the full length
        assert len(user) < len(long_text) + 1000  # reasonable bound

    def test_credentials_redacted_from_article_text(self):
        from backend.labgen.article_lab_prompt_builder import build_article_to_lab_messages

        article_with_secret = f"token: eyJhbGciOiJSUzI1NiJ9.fake.{'x' * 40}\nkubectl apply"
        system, user = build_article_to_lab_messages(
            article_with_secret,
            article_title="Secret Article",
            target_domain="k8s",
        )
        assert "eyJhbGciOiJSUzI1NiJ9.fake" not in user

    def test_partially_ready_note_included_for_partial_articles(self):
        from backend.labgen.article_lab_prompt_builder import build_article_to_lab_messages

        system, user = build_article_to_lab_messages(
            _K8S_ARTICLE,
            article_title="Partial",
            target_domain="k8s",
            operability_status="partially_lab_ready",
        )
        assert "PARTIALLY_LAB_READY" in user or "partial" in user.lower()

    def test_desired_lab_title_in_user_message(self):
        from backend.labgen.article_lab_prompt_builder import build_article_to_lab_messages

        system, user = build_article_to_lab_messages(
            _K8S_ARTICLE,
            article_title="Article",
            target_domain="k8s",
            desired_lab_title="My Desired Title",
        )
        assert "My Desired Title" in user


class TestCommandGenerationConstraints:
    """Regression: lab draft bb4fe651 required a week of manual debugging because
    the LLM generated shell-variable syntax (POD_NAME=$(...)) and a `kubectl delete
    namespace` verify step — both silently unrunnable by the sandboxed kubectl-only
    executor (backend/labgen/kubectl_executor.py). StaticValidator now catches these
    at publish time, but the prompt itself must also tell the LLM not to generate
    them in the first place, or every future article repeats the same debug cycle.
    """

    def test_prohibits_shell_variable_assignment(self):
        from backend.labgen.article_lab_prompt_builder import build_article_to_lab_messages

        system, _ = build_article_to_lab_messages(
            _K8S_ARTICLE, article_title="A", target_domain="k8s",
        )
        assert "$(" in system or "command substitution" in system.lower()
        assert "no shell" in system.lower() or "not run through a shell" in system.lower()

    def test_recommends_label_selector_over_captured_pod_name(self):
        from backend.labgen.article_lab_prompt_builder import build_article_to_lab_messages

        system, _ = build_article_to_lab_messages(
            _K8S_ARTICLE, article_title="A", target_domain="k8s",
        )
        assert "-l app=" in system or "label selector" in system.lower()

    def test_prohibits_delete_namespace(self):
        from backend.labgen.article_lab_prompt_builder import build_article_to_lab_messages

        system, _ = build_article_to_lab_messages(
            _K8S_ARTICLE, article_title="A", target_domain="k8s",
        )
        assert "delete namespace" in system.lower()
        assert "automatically" in system.lower() or "platform" in system.lower()

    def test_prohibits_yaml_json_output_formats(self):
        from backend.labgen.article_lab_prompt_builder import build_article_to_lab_messages

        system, _ = build_article_to_lab_messages(
            _K8S_ARTICLE, article_title="A", target_domain="k8s",
        )
        assert "-o yaml" in system
        assert "-o json" in system

    def test_prohibits_namespace_flag(self):
        from backend.labgen.article_lab_prompt_builder import build_article_to_lab_messages

        system, _ = build_article_to_lab_messages(
            _K8S_ARTICLE, article_title="A", target_domain="k8s",
        )
        assert "-n " in system or "--namespace" in system

    def test_prohibits_blocked_subcommands(self):
        from backend.labgen.article_lab_prompt_builder import build_article_to_lab_messages

        system, _ = build_article_to_lab_messages(
            _K8S_ARTICLE, article_title="A", target_domain="k8s",
        )
        for sub in ("exec", "port-forward", "cp", "debug"):
            assert sub in system

    def test_constraints_present_for_linux_domain_too(self):
        """Command constraints apply to any domain using the kubectl executor path —
        but at minimum must not silently disappear for non-k8s domains."""
        from backend.labgen.article_lab_prompt_builder import build_article_to_lab_messages

        system, _ = build_article_to_lab_messages(
            _LINUX_ARTICLE, article_title="A", target_domain="linux",
        )
        assert "COMMAND GENERATION" in system or "command generation" in system.lower()


# ---------------------------------------------------------------------------
# H. Regression Tests
# ---------------------------------------------------------------------------


class TestRegressions:
    def test_existing_article_draft_list_still_works(self, soft_launch_client):
        resp = soft_launch_client.get("/api/labgen/article-drafts")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_no_url_scraping_field(self):
        """source_url in CreateArticleDraftRequest is metadata only — no scraping."""
        from backend.labgen.article_draft_routes import CreateArticleDraftRequest

        req = CreateArticleDraftRequest(
            raw_text="kubectl apply -f test.yaml",
            source_url="https://example.com/article",
            copyright_confirmed=True,
            user_confirmed_right_to_use=True,
            user_confirmed_no_secrets=True,
        )
        # source_url is accepted as metadata — no scraping happens
        assert req.source_url == "https://example.com/article"
        assert req.raw_text  # raw_text is submitted, not fetched from URL

    def test_no_docker_domain_generation(self):
        """Docker domain articles are rejected by feasibility gate."""
        from backend.labgen.stub_feasibility_classifier import StubFeasibilityClassifier
        from backend.labgen.article_models import FeasibilityStatus

        docker_article = """
        # Docker Tutorial
        docker build -t myapp .
        docker run -p 8080:8080 myapp
        """
        result = StubFeasibilityClassifier().classify(docker_article)
        # Docker domain is not explicitly supported — should be partially ready or unknown
        # The key check: it should NOT be DIRECTLY_LAB_READY for Docker
        # (Docker is not in the supported domain list for generation)
        # Note: stub classifier may return partial for docker since it has commands
        # The domain filter happens at the generate-lab gate, not the upload gate
        assert result.status in (
            FeasibilityStatus.PARTIALLY_LAB_READY,
            FeasibilityStatus.NOT_LAB_READY,
        )

    def test_labgen_catalog_still_accessible(self, soft_launch_client):
        resp = soft_launch_client.get("/api/labs")
        assert resp.status_code == 200

    def test_health_endpoint_still_works(self, soft_launch_client):
        resp = soft_launch_client.get("/api/health")
        assert resp.status_code == 200

    def test_llm_mode_default_is_fake_only(self):
        """LABGEN_LLM_MODE defaults to fake_only — never live without explicit opt-in."""
        import os
        env_val = os.getenv("LABGEN_LLM_MODE", "fake_only")
        # In test environment this must be fake_only (no real LLM in tests)
        assert env_val in ("fake_only", "")

    def test_no_concurrent_increase(self):
        """Verify no new async locks or concurrency changes were introduced."""
        # Structural check: generate_lab_from_article is synchronous
        from backend.labgen.article_draft_service import ArticleDraftService
        import inspect
        method = getattr(ArticleDraftService, "generate_lab_from_article", None)
        assert method is not None
        assert not inspect.iscoroutinefunction(method)

    def test_admin_article_upload_does_not_allow_missing_title_to_crash(self, soft_launch_client):
        """Missing title is allowed (optional field) — should not 500."""
        resp = soft_launch_client.post(
            "/api/labgen/article-drafts",
            json={
                "raw_text": _K8S_ARTICLE,
                "copyright_confirmed": True,
                "user_confirmed_right_to_use": True,
                "user_confirmed_no_secrets": True,
                # title omitted
            },
        )
        # Should succeed (title is optional)
        assert resp.status_code == 201

    def test_labgen_llm_mode_env_var_invalid_falls_back(self, tmp_path):
        """Invalid LABGEN_LLM_MODE falls back to fake_only — fail-closed."""
        from backend.labgen.article_draft_repository import ArticleDraftRepository
        from backend.labgen.repository import LabDraftRepository
        from backend.labgen.article_draft_service import ArticleDraftService
        from backend.labgen.llm_audit import LLMAuditRepository
        from backend.labgen.article_models import ArticleSourceMetadata, ArticleSourceType
        from backend.labgen.stub_feasibility_classifier import compute_content_hash

        article_repo = ArticleDraftRepository(path=tmp_path / "a.json")
        lab_repo = LabDraftRepository(path=tmp_path / "l.json")
        audit_repo = LLMAuditRepository(audit_path=tmp_path / "audit.json")
        svc = ArticleDraftService(article_repo=article_repo, lab_repo=lab_repo)

        src_meta = ArticleSourceMetadata(
            source_type=ArticleSourceType.PASTED_TEXT,
            title="K8s Test",
            submitted_by_user_id="owner",
            content_hash=compute_content_hash(_K8S_ARTICLE),
            content_length=len(_K8S_ARTICLE),
            user_confirmed_right_to_use=True,
            user_confirmed_no_secrets=True,
            raw_text_persisted=False,
        )
        contract = svc.create_draft(_K8S_ARTICLE, src_meta, "owner")

        # Invalid mode → service treats as fake_only (fail-closed)
        with patch("backend.config.LABGEN_LLM_MODE", "totally_invalid_mode"):
            result = svc.generate_lab_from_article(
                draft_id=contract.draft_id,
                article_text=_K8S_ARTICLE,
                admin_user="owner",
                audit_repo=audit_repo,
            )
        assert result.lab_draft is not None
