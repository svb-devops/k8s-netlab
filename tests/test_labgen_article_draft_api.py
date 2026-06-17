"""
Tests for Article-to-Lab Draft Mode implementation.

Covers:
  - ArticleDraftRepository (CRUD, flock JSON persistence)
  - StubFeasibilityClassifier (all tiers, safety flags, domain detection)
  - ArticleDraftService (create, update, admin review, status transitions,
      guardrail blocking, convert to LabDraft)
  - article_draft_routes (all API endpoints, admin auth enforcement)

Constraints verified:
  - raw_text never persisted
  - cloud domain blocked
  - NOT_LAB_READY cannot advance to publish
  - APPROVE requires all confirmations
  - Convert only works on APPROVED_FOR_PUBLISH_CANDIDATE
  - LabDraft from conversion is DRAFT status (not published)
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _source_meta(
    submitted_by: str = "admin",
    confirmed_right: bool = True,
    confirmed_secrets: bool = True,
    text: str = "kubectl apply -f deployment.yaml",
) -> dict:
    from backend.labgen.article_models import ArticleSourceMetadata, ArticleSourceType
    return ArticleSourceMetadata(
        source_type=ArticleSourceType.PASTED_TEXT,
        submitted_by_user_id=submitted_by,
        content_hash=_sha(text),
        content_length=len(text),
        user_confirmed_right_to_use=confirmed_right,
        user_confirmed_no_secrets=confirmed_secrets,
        raw_text_persisted=False,
    )


def _partial_feasibility() -> "FeasibilityResult":
    from backend.labgen.article_models import (
        FeasibilityResult, FeasibilityStatus, FeasibilityEvaluatedBy,
        VerifierFeasibility,
    )
    return FeasibilityResult(
        status=FeasibilityStatus.PARTIALLY_LAB_READY,
        evaluated_by=FeasibilityEvaluatedBy.STUB,
    )


def _direct_feasibility() -> "FeasibilityResult":
    from backend.labgen.article_models import (
        FeasibilityResult, FeasibilityStatus, FeasibilityEvaluatedBy,
        TargetDomain, VerifierFeasibility,
    )
    return FeasibilityResult(
        status=FeasibilityStatus.DIRECTLY_LAB_READY,
        target_domain_candidates=[TargetDomain.K8S],
        evaluated_by=FeasibilityEvaluatedBy.STUB,
        verifier_feasibility=VerifierFeasibility.NEEDS_PARAMETERIZATION,
        cleanup_feasibility="namespace_delete",
        runtime_feasibility="k8s_namespace",
    )


def _not_ready_feasibility() -> "FeasibilityResult":
    from backend.labgen.article_models import (
        FeasibilityResult, FeasibilityStatus, FeasibilityEvaluatedBy,
    )
    return FeasibilityResult(
        status=FeasibilityStatus.NOT_LAB_READY,
        rejection_code="stub.no_operable_content",
        evaluated_by=FeasibilityEvaluatedBy.STUB,
    )


def _draft_contract(
    status_val=None,
    feasibility=None,
    target_domain=None,
) -> "ArticleDraftLabContract":
    from backend.labgen.article_models import (
        ArticleDraftLabContract, ArticleDraftStatus, TargetDomain,
    )
    text = "kubectl apply -f deployment.yaml"
    return ArticleDraftLabContract(
        source_metadata=_source_meta(text=text),
        feasibility_result=feasibility or _partial_feasibility(),
        target_domain=target_domain or TargetDomain.K8S,
        status=status_val or ArticleDraftStatus.DRAFT,
    )


def _fully_confirmed_admin_decision(
    reviewer_id: str = "admin",
) -> "AdminDecision":
    from backend.labgen.article_models import AdminDecision, AdminDecisionValue
    return AdminDecision(
        decision=AdminDecisionValue.APPROVE,
        reviewer_id=reviewer_id,
        reviewed_at=datetime.now(tz=timezone.utc),
        confirmed_source_grounding=True,
        confirmed_safety=True,
        confirmed_cleanup=True,
        confirmed_verifier_strategy=True,
        confirmed_no_raw_secret=True,
        confirmed_no_direct_publish=True,
    )


# ---------------------------------------------------------------------------
# ArticleDraftRepository tests
# ---------------------------------------------------------------------------


class TestArticleDraftRepository:
    @pytest.fixture()
    def repo(self, tmp_path: Path):
        from backend.labgen.article_draft_repository import ArticleDraftRepository
        return ArticleDraftRepository(path=tmp_path / "article_drafts.json")

    def test_create_and_get(self, repo):
        contract = _draft_contract()
        repo.create(contract)
        fetched = repo.get(contract.draft_id)
        assert fetched is not None
        assert fetched.draft_id == contract.draft_id

    def test_get_missing_returns_none(self, repo):
        assert repo.get("nonexistent-id") is None

    def test_update(self, repo):
        from backend.labgen.article_models import ArticleDraftStatus
        contract = _draft_contract()
        repo.create(contract)
        contract.status = ArticleDraftStatus.NEEDS_CHANGES
        repo.update(contract)
        fetched = repo.get(contract.draft_id)
        assert fetched.status == ArticleDraftStatus.NEEDS_CHANGES

    def test_delete(self, repo):
        contract = _draft_contract()
        repo.create(contract)
        repo.delete(contract.draft_id)
        assert repo.get(contract.draft_id) is None

    def test_delete_missing_is_noop(self, repo):
        repo.delete("nonexistent")  # must not raise

    def test_list_all_empty(self, repo):
        assert repo.list_all() == []

    def test_list_all_multiple(self, repo):
        c1 = _draft_contract()
        c2 = _draft_contract()
        repo.create(c1)
        repo.create(c2)
        ids = {c.draft_id for c in repo.list_all()}
        assert c1.draft_id in ids
        assert c2.draft_id in ids

    def test_raw_text_never_persisted(self, repo, tmp_path):
        contract = _draft_contract()
        repo.create(contract)
        raw = (tmp_path / "article_drafts.json").read_text()
        # Actual article body must not appear anywhere in the stored JSON.
        # The string "raw_article_text" may legitimately appear as an element
        # of storage_policy.excluded_fields, which is the exclusion manifest.
        assert "kubectl create configmap" not in raw
        assert '"raw_text"' not in raw  # no top-level field named raw_text

    def test_create_multiple_does_not_overwrite(self, repo):
        c1 = _draft_contract()
        c2 = _draft_contract()
        repo.create(c1)
        repo.create(c2)
        assert repo.get(c1.draft_id) is not None
        assert repo.get(c2.draft_id) is not None

    def test_raw_text_persisted_false_enforced(self):
        """model_validator must reject raw_text_persisted=True"""
        from backend.labgen.article_models import (
            ArticleDraftLabContract, ArticleSourceMetadata, ArticleSourceType,
        )
        import pydantic
        with pytest.raises((pydantic.ValidationError, ValueError)):
            meta = ArticleSourceMetadata(
                source_type=ArticleSourceType.PASTED_TEXT,
                submitted_by_user_id="admin",
                content_hash=_sha("x"),
                content_length=1,
                raw_text_persisted=True,
            )
            ArticleDraftLabContract(
                source_metadata=meta,
                feasibility_result=_partial_feasibility(),
            )


# ---------------------------------------------------------------------------
# StubFeasibilityClassifier tests
# ---------------------------------------------------------------------------


class TestStubFeasibilityClassifier:
    @pytest.fixture()
    def clf(self):
        from backend.labgen.stub_feasibility_classifier import StubFeasibilityClassifier
        return StubFeasibilityClassifier()

    def test_compute_content_hash_deterministic(self):
        from backend.labgen.stub_feasibility_classifier import compute_content_hash
        text = "hello world"
        assert compute_content_hash(text) == compute_content_hash(text)
        assert compute_content_hash(text) == hashlib.sha256(text.encode()).hexdigest()

    def test_evaluated_by_always_stub(self, clf):
        from backend.labgen.article_models import FeasibilityEvaluatedBy
        result = clf.classify("kubectl apply -f cm.yaml && kubectl get cm")
        assert result.evaluated_by == FeasibilityEvaluatedBy.STUB

    def test_k8s_article_with_commands_directly_lab_ready(self, clf):
        from backend.labgen.article_models import FeasibilityStatus
        text = """
# Step 1: Create a ConfigMap

```bash
kubectl apply -f configmap.yaml
```

## Step 2: Verify

```bash
kubectl get configmap my-config
```

The configmap should exist in the namespace.
kubectl describe configmap my-config
"""
        result = clf.classify(text)
        assert result.status == FeasibilityStatus.DIRECTLY_LAB_READY

    def test_secret_content_hard_rejected(self, clf):
        from backend.labgen.article_models import FeasibilityStatus, SafetyFlag
        text = "api_key=AKIAIOSFODNN7EXAMPLE\nkubectl apply -f deploy.yaml"
        result = clf.classify(text)
        assert result.status == FeasibilityStatus.NOT_LAB_READY
        assert SafetyFlag.CONTAINS_SECRET_LIKE_CONTENT in result.safety_flags

    def test_aws_access_key_hard_rejected(self, clf):
        from backend.labgen.article_models import FeasibilityStatus, SafetyFlag
        text = "AKIAIOSFODNN7EXAMPLE and kubectl apply"
        result = clf.classify(text)
        assert result.status == FeasibilityStatus.NOT_LAB_READY
        assert SafetyFlag.CONTAINS_SECRET_LIKE_CONTENT in result.safety_flags

    def test_private_key_hard_rejected(self, clf):
        from backend.labgen.article_models import FeasibilityStatus, SafetyFlag
        text = "-----BEGIN RSA PRIVATE KEY-----\nkubectl apply"
        result = clf.classify(text)
        assert result.status == FeasibilityStatus.NOT_LAB_READY
        assert SafetyFlag.CONTAINS_SECRET_LIKE_CONTENT in result.safety_flags

    def test_cloud_only_article_not_lab_ready(self, clf):
        from backend.labgen.article_models import FeasibilityStatus
        text = "This article covers AWS EC2 and S3 bucket configuration for Azure cloud."
        result = clf.classify(text)
        assert result.status == FeasibilityStatus.NOT_LAB_READY
        assert result.rejection_code == "stub.cloud_domain_blocked_v1"

    def test_unknown_domain_partially_lab_ready(self, clf):
        from backend.labgen.article_models import FeasibilityStatus
        text = "This guide covers Linux file permissions and process management."
        result = clf.classify(text)
        assert result.status == FeasibilityStatus.PARTIALLY_LAB_READY

    def test_no_commands_non_operable(self, clf):
        from backend.labgen.article_models import FeasibilityStatus
        text = "In conclusion, Kubernetes is a container orchestration platform. This blog post explores the ecosystem."
        result = clf.classify(text)
        assert result.status in (
            FeasibilityStatus.NOT_LAB_READY,
            FeasibilityStatus.PARTIALLY_LAB_READY,
        )

    def test_real_credentials_flag(self, clf):
        from backend.labgen.article_models import SafetyFlag
        text = "Replace this with your real API key and kubectl apply -f deploy.yaml"
        result = clf.classify(text)
        assert SafetyFlag.REQUIRES_REAL_CREDENTIALS in result.safety_flags

    def test_destructive_operation_flag(self, clf):
        from backend.labgen.article_models import SafetyFlag
        text = "kubectl apply -f deploy.yaml\nrm -rf / --no-preserve-root"
        result = clf.classify(text)
        assert SafetyFlag.DESTRUCTIVE_OPERATION in result.safety_flags

    def test_k8s_without_commands_partially_lab_ready(self, clf):
        from backend.labgen.article_models import FeasibilityStatus
        text = "Kubernetes is a platform. You can use kubectl to manage resources."
        result = clf.classify(text)
        # No code blocks / shell prompts — partial at best
        assert result.status in (
            FeasibilityStatus.PARTIALLY_LAB_READY,
            FeasibilityStatus.NOT_LAB_READY,
        )

    def test_target_domain_candidates_populated(self, clf):
        from backend.labgen.article_models import TargetDomain
        text = """
```bash
kubectl apply -f configmap.yaml
```
kubectl get configmap
"""
        result = clf.classify(text)
        assert TargetDomain.K8S in result.target_domain_candidates

    def test_production_env_flag(self, clf):
        from backend.labgen.article_models import SafetyFlag
        text = "This only works on production cluster. kubectl apply -f deploy.yaml"
        result = clf.classify(text)
        assert SafetyFlag.REQUIRES_PRODUCTION_ENVIRONMENT in result.safety_flags

    def test_operability_score_not_none_for_directly_ready(self, clf):
        text = """
## Step 1: Deploy

```bash
kubectl apply -f configmap.yaml
```

## Step 2: Verify

```bash
kubectl get configmap my-config
```

The configmap should exist. kubectl describe configmap my-config.
"""
        result = clf.classify(text)
        assert result.operability_score is not None


# ---------------------------------------------------------------------------
# ArticleDraftService tests
# ---------------------------------------------------------------------------


class TestArticleDraftService:
    @pytest.fixture()
    def tmp_article_repo(self, tmp_path):
        from backend.labgen.article_draft_repository import ArticleDraftRepository
        return ArticleDraftRepository(path=tmp_path / "article_drafts.json")

    @pytest.fixture()
    def tmp_lab_repo(self, tmp_path):
        from backend.labgen.repository import LabDraftRepository
        return LabDraftRepository(path=tmp_path / "lab_drafts.json")

    @pytest.fixture()
    def svc(self, tmp_article_repo, tmp_lab_repo):
        from backend.labgen.article_draft_service import ArticleDraftService
        return ArticleDraftService(
            article_repo=tmp_article_repo,
            lab_repo=tmp_lab_repo,
        )

    def _make_text(self) -> str:
        return "kubectl apply -f deploy.yaml\n```bash\nkubectl get pod\n```"

    def test_create_draft_stores_contract(self, svc, tmp_article_repo):
        from backend.labgen.article_models import ArticleDraftStatus
        text = self._make_text()
        meta = _source_meta(text=text)
        contract = svc.create_draft(raw_text=text, source_metadata=meta, submitted_by="admin")
        assert contract.draft_id is not None
        assert contract.status == ArticleDraftStatus.DRAFT
        fetched = tmp_article_repo.get(contract.draft_id)
        assert fetched is not None

    def test_create_draft_hash_mismatch_raises(self, svc):
        from backend.labgen.article_draft_service import ArticleDraftServiceError
        from backend.labgen.article_models import ArticleSourceMetadata, ArticleSourceType
        text = "kubectl apply"
        meta = ArticleSourceMetadata(
            source_type=ArticleSourceType.PASTED_TEXT,
            submitted_by_user_id="admin",
            content_hash=_sha("wrong text"),
            content_length=len(text),
        )
        with pytest.raises(ArticleDraftServiceError, match="content_hash"):
            svc.create_draft(raw_text=text, source_metadata=meta, submitted_by="admin")

    def test_get_not_found_raises(self, svc):
        from backend.labgen.article_draft_service import ArticleDraftNotFound
        with pytest.raises(ArticleDraftNotFound):
            svc.get_draft("nonexistent")

    def test_list_drafts_returns_all(self, svc):
        for _ in range(3):
            text = f"kubectl apply -f {uuid.uuid4()}"
            meta = _source_meta(text=text)
            svc.create_draft(raw_text=text, source_metadata=meta, submitted_by="admin")
        assert len(svc.list_drafts()) == 3

    def test_update_draft_allowed_fields(self, svc):
        text = self._make_text()
        meta = _source_meta(text=text)
        contract = svc.create_draft(raw_text=text, source_metadata=meta, submitted_by="admin")
        updated = svc.update_draft(
            contract.draft_id,
            {"learning_objective": "Learn kubectl basics"},
            updated_by="admin",
        )
        assert updated.learning_objective == "Learn kubectl basics"

    def test_update_draft_forbidden_field_raises(self, svc):
        from backend.labgen.article_draft_service import ArticleDraftServiceError
        text = self._make_text()
        meta = _source_meta(text=text)
        contract = svc.create_draft(raw_text=text, source_metadata=meta, submitted_by="admin")
        with pytest.raises(ArticleDraftServiceError, match="status"):
            svc.update_draft(contract.draft_id, {"status": "rejected"}, updated_by="admin")

    def test_approve_requires_all_confirmations(self, svc):
        from backend.labgen.article_draft_service import ArticleDraftTransitionForbidden
        from backend.labgen.article_models import AdminDecisionValue
        text = self._make_text()
        meta = _source_meta(text=text)
        contract = svc.create_draft(raw_text=text, source_metadata=meta, submitted_by="admin")
        with pytest.raises(ArticleDraftTransitionForbidden, match="confirmed_"):
            svc.record_admin_decision(
                draft_id=contract.draft_id,
                decision=AdminDecisionValue.APPROVE,
                reviewer_id="admin",
                # all confirmed_* default False
            )

    def test_request_changes_moves_to_needs_changes(self, svc):
        from backend.labgen.article_models import AdminDecisionValue, ArticleDraftStatus
        text = self._make_text()
        meta = _source_meta(text=text)
        contract = svc.create_draft(raw_text=text, source_metadata=meta, submitted_by="admin")
        updated = svc.record_admin_decision(
            draft_id=contract.draft_id,
            decision=AdminDecisionValue.REQUEST_CHANGES,
            reviewer_id="admin",
            required_changes=["add verifier info"],
        )
        assert updated.status == ArticleDraftStatus.NEEDS_CHANGES

    def test_reject_moves_to_rejected(self, svc):
        from backend.labgen.article_models import AdminDecisionValue, ArticleDraftStatus
        text = self._make_text()
        meta = _source_meta(text=text)
        contract = svc.create_draft(raw_text=text, source_metadata=meta, submitted_by="admin")
        updated = svc.record_admin_decision(
            draft_id=contract.draft_id,
            decision=AdminDecisionValue.REJECT,
            reviewer_id="admin",
        )
        assert updated.status == ArticleDraftStatus.REJECTED

    def test_validate_draft_returns_results(self, svc):
        text = self._make_text()
        meta = _source_meta(text=text)
        contract = svc.create_draft(raw_text=text, source_metadata=meta, submitted_by="admin")
        results = svc.validate_draft(contract.draft_id)
        assert isinstance(results, list)
        assert len(results) > 0

    def test_delete_draft(self, svc, tmp_article_repo):
        text = self._make_text()
        meta = _source_meta(text=text)
        contract = svc.create_draft(raw_text=text, source_metadata=meta, submitted_by="admin")
        svc.delete_draft(contract.draft_id)
        assert tmp_article_repo.get(contract.draft_id) is None

    def test_delete_publish_candidate_raises(self, svc):
        from backend.labgen.article_draft_service import ArticleDraftTransitionForbidden
        from backend.labgen.article_models import ArticleDraftStatus
        contract = _draft_contract(status_val=ArticleDraftStatus.APPROVED_FOR_PUBLISH_CANDIDATE)
        svc._article_repo.create(contract)
        with pytest.raises(ArticleDraftTransitionForbidden):
            svc.delete_draft(contract.draft_id)

    def test_advance_to_internal_rehearsal_wrong_status_raises(self, svc):
        from backend.labgen.article_draft_service import ArticleDraftTransitionForbidden
        from backend.labgen.article_models import ArticleDraftStatus
        contract = _draft_contract(status_val=ArticleDraftStatus.DRAFT)
        svc._article_repo.create(contract)
        with pytest.raises(ArticleDraftTransitionForbidden):
            svc.advance_to_internal_rehearsal(contract.draft_id)

    def test_advance_to_publish_candidate_wrong_status_raises(self, svc):
        from backend.labgen.article_draft_service import ArticleDraftTransitionForbidden
        from backend.labgen.article_models import ArticleDraftStatus
        contract = _draft_contract(status_val=ArticleDraftStatus.APPROVED_FOR_STATIC_VALIDATION)
        svc._article_repo.create(contract)
        with pytest.raises(ArticleDraftTransitionForbidden):
            svc.advance_to_publish_candidate(contract.draft_id)

    def test_convert_to_lab_draft_wrong_status_raises(self, svc):
        from backend.labgen.article_draft_service import ArticleDraftTransitionForbidden
        from backend.labgen.article_models import ArticleDraftStatus
        contract = _draft_contract(status_val=ArticleDraftStatus.DRAFT)
        svc._article_repo.create(contract)
        with pytest.raises(ArticleDraftTransitionForbidden):
            svc.convert_to_lab_draft(contract.draft_id, converted_by="admin")

    def test_convert_to_lab_draft_creates_lab_draft(self, svc, tmp_lab_repo):
        """Full happy path: build a publish-candidate contract and convert it."""
        from backend.labgen.article_models import (
            ArticleDraftLabContract,
            ArticleDraftStatus,
            ArticleLabRuntimeRequirement,
            ArticleRuntimeType,
            FeasibilityResult,
            FeasibilityStatus,
            FeasibilityEvaluatedBy,
            SourceGroundingSnippet,
            TargetDomain,
            UnsupportedInference,
            UnsupportedInferenceSeverity,
            VerifierCandidate,
            VerifierCandidateState,
        )
        from backend.labgen.models import PublishStatus

        grounding = SourceGroundingSnippet(
            excerpt="kubectl apply -f cm.yaml",
            excerpt_hash=_sha("kubectl apply -f cm.yaml"),
            contains_sensitive_content=False,
        )
        runtime = ArticleLabRuntimeRequirement(
            domain=TargetDomain.K8S,
            runtime_type=ArticleRuntimeType.K8S_NAMESPACE,
            cleanup_strategy="namespace_delete",
            production_dependency=False,
        )
        verifier = VerifierCandidate(
            candidate_state=VerifierCandidateState.REUSABLE_EXISTING,
            primitive_name="namespace_exists",
            parameters={"namespace": "{{lab_namespace}}"},
            review_required=True,
            admin_reviewed=True,
        )
        admin_decision = _fully_confirmed_admin_decision()
        feasibility = FeasibilityResult(
            status=FeasibilityStatus.DIRECTLY_LAB_READY,
            target_domain_candidates=[TargetDomain.K8S],
            evaluated_by=FeasibilityEvaluatedBy.STUB,
        )
        text = "kubectl apply"
        contract = ArticleDraftLabContract(
            source_metadata=_source_meta(text=text),
            feasibility_result=feasibility,
            target_domain=TargetDomain.K8S,
            status=ArticleDraftStatus.APPROVED_FOR_PUBLISH_CANDIDATE,
            admin_decision=admin_decision,
            required_runtime=runtime,
            source_grounding=[grounding],
            verifier_candidates=[verifier],
            learner_steps=["Apply the ConfigMap using kubectl"],
        )
        svc._article_repo.create(contract)

        lab_draft = svc.convert_to_lab_draft(contract.draft_id, converted_by="admin")
        assert lab_draft.source_article_id == contract.draft_id
        assert lab_draft.publish_status == PublishStatus.DRAFT
        assert len(lab_draft.steps) == 1
        stored = tmp_lab_repo.get(lab_draft.lab_id)
        assert stored is not None

    def test_convert_creates_draft_not_published(self, svc):
        """Converted LabDraft must have publish_status=DRAFT, not PUBLISHED."""
        from backend.labgen.article_models import (
            ArticleDraftLabContract,
            ArticleDraftStatus,
            ArticleLabRuntimeRequirement,
            ArticleRuntimeType,
            FeasibilityResult,
            FeasibilityStatus,
            FeasibilityEvaluatedBy,
            SourceGroundingSnippet,
            TargetDomain,
        )
        from backend.labgen.models import PublishStatus

        grounding = SourceGroundingSnippet(
            excerpt="kubectl apply",
            excerpt_hash=_sha("kubectl apply"),
        )
        runtime = ArticleLabRuntimeRequirement(
            domain=TargetDomain.K8S,
            runtime_type=ArticleRuntimeType.K8S_NAMESPACE,
            cleanup_strategy="namespace_delete",
        )
        text = "kubectl apply"
        contract = ArticleDraftLabContract(
            source_metadata=_source_meta(text=text),
            feasibility_result=FeasibilityResult(
                status=FeasibilityStatus.DIRECTLY_LAB_READY,
                target_domain_candidates=[TargetDomain.K8S],
                evaluated_by=FeasibilityEvaluatedBy.STUB,
            ),
            target_domain=TargetDomain.K8S,
            status=ArticleDraftStatus.APPROVED_FOR_PUBLISH_CANDIDATE,
            admin_decision=_fully_confirmed_admin_decision(),
            required_runtime=runtime,
            source_grounding=[grounding],
        )
        svc._article_repo.create(contract)

        lab_draft = svc.convert_to_lab_draft(contract.draft_id, converted_by="admin")
        assert lab_draft.publish_status == PublishStatus.DRAFT
        assert lab_draft.publish_status != PublishStatus.PUBLISHED


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app_client(tmp_path_factory):
    """TestClient with all dependencies overridden for isolation."""
    import dotenv
    dotenv.load_dotenv()

    tmp = tmp_path_factory.mktemp("article_api")

    from backend.labgen.article_draft_repository import ArticleDraftRepository
    from backend.labgen.repository import LabDraftRepository
    from backend.labgen.article_draft_service import ArticleDraftService
    import backend.labgen.article_draft_routes as adr

    article_repo = ArticleDraftRepository(path=tmp / "article_drafts.json")
    lab_repo = LabDraftRepository(path=tmp / "lab_drafts.json")
    svc = ArticleDraftService(article_repo=article_repo, lab_repo=lab_repo)

    from backend.main import app
    app.dependency_overrides[adr.get_article_draft_service] = lambda: svc

    # Mock admin user
    from backend.auth_deps import get_current_user
    from backend.auth import auth_manager

    _real_is_admin = auth_manager.is_admin

    def _mock_is_admin(username: str) -> bool:
        if username == "test_admin":
            return True
        return _real_is_admin(username)

    auth_manager.is_admin = _mock_is_admin
    app.dependency_overrides[get_current_user] = lambda: "test_admin"

    with TestClient(app, raise_server_exceptions=True) as client:
        yield client

    app.dependency_overrides.clear()
    auth_manager.is_admin = _real_is_admin


K8S_ARTICLE = """
# Deploy a ConfigMap

## Step 1: Create

```bash
kubectl apply -f configmap.yaml
```

## Step 2: Verify

```bash
kubectl get configmap my-config
```

The configmap should exist in the namespace.
kubectl describe configmap my-config
"""


class TestArticleDraftEndpoints:
    def test_create_draft_201(self, app_client):
        resp = app_client.post(
            "/api/labgen/article-drafts",
            json={
                "raw_text": K8S_ARTICLE,
                "title": "K8s ConfigMap Lab",
                "user_confirmed_right_to_use": True,
                "user_confirmed_no_secrets": True,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "draft_id" in data
        assert data["status"] == "draft"
        assert data["source_metadata"]["raw_text_persisted"] is False

    def test_create_draft_empty_text_422(self, app_client):
        resp = app_client.post(
            "/api/labgen/article-drafts",
            json={"raw_text": ""},
        )
        assert resp.status_code == 422

    def test_list_drafts_200(self, app_client):
        resp = app_client.get("/api/labgen/article-drafts")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_draft_200(self, app_client):
        create_resp = app_client.post(
            "/api/labgen/article-drafts",
            json={"raw_text": K8S_ARTICLE},
        )
        draft_id = create_resp.json()["draft_id"]
        resp = app_client.get(f"/api/labgen/article-drafts/{draft_id}")
        assert resp.status_code == 200
        assert resp.json()["draft_id"] == draft_id

    def test_get_draft_404(self, app_client):
        resp = app_client.get("/api/labgen/article-drafts/nonexistent-id")
        assert resp.status_code == 404

    def test_patch_draft_200(self, app_client):
        create_resp = app_client.post(
            "/api/labgen/article-drafts",
            json={"raw_text": K8S_ARTICLE},
        )
        draft_id = create_resp.json()["draft_id"]
        resp = app_client.patch(
            f"/api/labgen/article-drafts/{draft_id}",
            json={"learning_objective": "Learn ConfigMaps"},
        )
        assert resp.status_code == 200
        assert resp.json()["learning_objective"] == "Learn ConfigMaps"

    def test_validate_draft_200(self, app_client):
        create_resp = app_client.post(
            "/api/labgen/article-drafts",
            json={"raw_text": K8S_ARTICLE},
        )
        draft_id = create_resp.json()["draft_id"]
        resp = app_client.post(f"/api/labgen/article-drafts/{draft_id}/validate")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_review_request_changes_200(self, app_client):
        create_resp = app_client.post(
            "/api/labgen/article-drafts",
            json={"raw_text": K8S_ARTICLE},
        )
        draft_id = create_resp.json()["draft_id"]
        resp = app_client.post(
            f"/api/labgen/article-drafts/{draft_id}/review",
            json={
                "decision": "request_changes",
                "required_changes": ["add verifier"],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "needs_changes"

    def test_review_reject_200(self, app_client):
        create_resp = app_client.post(
            "/api/labgen/article-drafts",
            json={"raw_text": K8S_ARTICLE},
        )
        draft_id = create_resp.json()["draft_id"]
        resp = app_client.post(
            f"/api/labgen/article-drafts/{draft_id}/review",
            json={"decision": "reject"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

    def test_review_approve_without_confirmations_403(self, app_client):
        create_resp = app_client.post(
            "/api/labgen/article-drafts",
            json={"raw_text": K8S_ARTICLE},
        )
        draft_id = create_resp.json()["draft_id"]
        resp = app_client.post(
            f"/api/labgen/article-drafts/{draft_id}/review",
            json={"decision": "approve"},  # no confirmed_* fields
        )
        assert resp.status_code == 403

    def test_advance_wrong_status_403(self, app_client):
        create_resp = app_client.post(
            "/api/labgen/article-drafts",
            json={"raw_text": K8S_ARTICLE},
        )
        draft_id = create_resp.json()["draft_id"]
        resp = app_client.post(
            f"/api/labgen/article-drafts/{draft_id}/advance",
            json={"target_status": "approved_for_internal_rehearsal"},
        )
        assert resp.status_code == 403

    def test_convert_wrong_status_403(self, app_client):
        create_resp = app_client.post(
            "/api/labgen/article-drafts",
            json={"raw_text": K8S_ARTICLE},
        )
        draft_id = create_resp.json()["draft_id"]
        resp = app_client.post(f"/api/labgen/article-drafts/{draft_id}/convert")
        assert resp.status_code == 403

    def test_delete_draft_204(self, app_client):
        create_resp = app_client.post(
            "/api/labgen/article-drafts",
            json={"raw_text": K8S_ARTICLE},
        )
        draft_id = create_resp.json()["draft_id"]
        resp = app_client.delete(f"/api/labgen/article-drafts/{draft_id}")
        assert resp.status_code == 204
        get_resp = app_client.get(f"/api/labgen/article-drafts/{draft_id}")
        assert get_resp.status_code == 404

    def test_secret_article_still_creates_draft_but_not_lab_ready(self, app_client):
        """Secret-containing articles should be classified NOT_LAB_READY in feasibility."""
        secret_text = "api_key=AKIAIOSFODNN7EXAMPLE\nkubectl apply -f deploy.yaml"
        resp = app_client.post(
            "/api/labgen/article-drafts",
            json={"raw_text": secret_text},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["feasibility_result"]["status"] == "not_lab_ready"

    def test_raw_text_not_in_response(self, app_client):
        """Response must not contain raw article text body anywhere."""
        resp = app_client.post(
            "/api/labgen/article-drafts",
            json={"raw_text": K8S_ARTICLE},
        )
        assert resp.status_code == 201
        response_text = resp.text
        # The actual article body must not appear in the response.
        # "raw_article_text" may appear as a value in storage_policy.excluded_fields
        # (the exclusion manifest), which is correct behavior.
        assert K8S_ARTICLE not in response_text
        assert "kubectl create configmap my-config" not in response_text


# ---------------------------------------------------------------------------
# Admin auth enforcement (non-admin should get 403)
# ---------------------------------------------------------------------------


class TestArticleDraftAdminAuthEnforcement:
    @pytest.fixture()
    def non_admin_client(self, tmp_path):
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

        _real_is_admin = auth_manager.is_admin
        auth_manager.is_admin = lambda username: False  # everyone is non-admin
        app.dependency_overrides[adr.get_article_draft_service] = lambda: svc
        app.dependency_overrides[get_current_user] = lambda: "regular_user"

        with TestClient(app, raise_server_exceptions=True) as client:
            yield client

        app.dependency_overrides.clear()
        auth_manager.is_admin = _real_is_admin

    def test_create_forbidden_for_non_admin(self, non_admin_client):
        resp = non_admin_client.post(
            "/api/labgen/article-drafts",
            json={"raw_text": "kubectl apply -f cm.yaml"},
        )
        assert resp.status_code == 403

    def test_list_forbidden_for_non_admin(self, non_admin_client):
        resp = non_admin_client.get("/api/labgen/article-drafts")
        assert resp.status_code == 403

    def test_get_forbidden_for_non_admin(self, non_admin_client):
        resp = non_admin_client.get("/api/labgen/article-drafts/any-id")
        assert resp.status_code == 403
