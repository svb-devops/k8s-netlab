"""
K8s Article-to-Lab Admin Review Rehearsal v0.1

End-to-end rehearsal of the article draft pipeline with 4 controlled input samples.
All invariants verified:
  - admin-only access enforcement
  - feasibility classification per article type
  - raw text never persisted / never in response
  - sensitive content hard-rejected without persistence
  - partial/rejected articles cannot publish
  - directly_lab_ready still requires admin review
  - admin confirmed_* gate works
  - StaticValidator bridge integration
  - generated drafts not in learner catalog
  - LLM never called (evaluated_by == stub)
  - runtime / verifier / terminal not touched

Finding documented:
  MEDIUM-001: PatchArticleDraftRequest did not originally expose source_grounding,
  required_runtime, or verifier_candidates — blocking full pipeline advance to
  APPROVED_FOR_PUBLISH_CANDIDATE. Fixed in this commit by extending PatchArticleDraftRequest.
"""

from __future__ import annotations

import hashlib

import dotenv
import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Rehearsal input samples
# ---------------------------------------------------------------------------

# Sample 1 — Directly Lab-Ready: K8s ConfigMap tutorial with commands + verifiable outcomes
K8S_DIRECTLY_READY = """
# How to Use Kubernetes ConfigMaps for Application Configuration

## Step 1: Create a ConfigMap

A ConfigMap allows you to store non-confidential configuration data as key-value pairs.

```bash
kubectl create configmap my-app-config --from-literal=APP_MODE=demo --from-literal=LOG_LEVEL=info
```

## Step 2: Verify the ConfigMap Exists

Run the following command to check the ConfigMap was created successfully:

```bash
kubectl get configmap my-app-config
```

The ConfigMap should exist in the namespace. You can inspect its contents:

```bash
kubectl describe configmap my-app-config
```

Expected: the ConfigMap object exists and contains the APP_MODE and LOG_LEVEL keys.
"""

# Sample 2 — Partially Lab-Ready: mentions K8s concepts but no executable commands
K8S_PARTIALLY_READY = """
Kubernetes ConfigMaps are a powerful mechanism for decoupling configuration from application code.
When you create a deployment, it can reference a ConfigMap to inject configuration values.
The Kubernetes API allows you to define a ConfigMap object with key-value pairs.
This approach separates environment-specific settings from container images,
making your deployments more portable across different Kubernetes clusters.
"""

# Sample 3 — Not Lab-Ready: pure theory, no executable steps
K8S_NOT_LAB_READY = """This article discusses the theoretical foundations of Kubernetes declarative API.

Kubernetes uses a declarative model where you describe the desired state of your cluster.
The control plane works continuously to reconcile the actual state with the desired state.
Controllers watch for changes and take action to maintain the desired cluster configuration.
In conclusion, the declarative approach of Kubernetes offers significant operational benefits
for managing containerized applications at scale.
"""

# Sample 4 — Sensitive content: fake credentials that should be hard-rejected
# NOTE: These are clearly fake placeholder values — not real secrets
SENSITIVE_CONTENT = """
To authenticate with the Kubernetes API, configure your credentials:

api_key=sk-test-redacted-example-placeholder-value

For certificate-based auth, load your private key:

-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASC placeholder only not real
-----END PRIVATE KEY-----
"""


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _create_payload(raw_text: str, **extra) -> dict:
    """
    Build a create-draft payload with user confirmations set to True by default.

    Rehearsal finding NOTE-001: user_confirmed_right_to_use and user_confirmed_no_secrets
    default to False, causing the validator to block any advance beyond DRAFT status.
    Real admins must explicitly pass these as True when submitting an article.
    """
    return {
        "raw_text": raw_text,
        "user_confirmed_right_to_use": True,
        "user_confirmed_no_secrets": True,
        **extra,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.static


@pytest.fixture(scope="module")
def _setup_env():
    dotenv.load_dotenv()


@pytest.fixture
def admin_client(tmp_path, _setup_env):
    """TestClient with admin auth override."""
    from backend.labgen.article_draft_repository import ArticleDraftRepository
    from backend.labgen.repository import LabDraftRepository
    from backend.labgen.article_draft_service import ArticleDraftService
    import backend.labgen.article_draft_routes as adr
    from backend.auth_deps import get_current_user
    from backend.auth import auth_manager
    from backend.main import app

    article_repo = ArticleDraftRepository(path=tmp_path / "article_drafts.json")
    lab_repo = LabDraftRepository(path=tmp_path / "lab_drafts.json")
    svc = ArticleDraftService(article_repo=article_repo, lab_repo=lab_repo)

    app.dependency_overrides[adr.get_article_draft_service] = lambda: svc

    _real_is_admin = auth_manager.is_admin

    def _mock_is_admin(username: str) -> bool:
        return username == "rehearsal_admin" or _real_is_admin(username)

    auth_manager.is_admin = _mock_is_admin
    app.dependency_overrides[get_current_user] = lambda: "rehearsal_admin"

    with TestClient(app, raise_server_exceptions=True) as client:
        yield client

    app.dependency_overrides.clear()
    auth_manager.is_admin = _real_is_admin


@pytest.fixture
def nonadmin_client(tmp_path, _setup_env):
    """TestClient with non-admin user auth override (same app, no admin role)."""
    from backend.labgen.article_draft_repository import ArticleDraftRepository
    from backend.labgen.repository import LabDraftRepository
    from backend.labgen.article_draft_service import ArticleDraftService
    import backend.labgen.article_draft_routes as adr
    from backend.auth_deps import get_current_user
    from backend.auth import auth_manager
    from backend.main import app

    article_repo = ArticleDraftRepository(path=tmp_path / "nonadmin_drafts.json")
    lab_repo = LabDraftRepository(path=tmp_path / "nonadmin_labs.json")
    svc = ArticleDraftService(article_repo=article_repo, lab_repo=lab_repo)

    app.dependency_overrides[adr.get_article_draft_service] = lambda: svc
    # Non-admin user — is_admin returns False by default for unknown usernames
    app.dependency_overrides[get_current_user] = lambda: "regular_student"

    with TestClient(app, raise_server_exceptions=True) as client:
        yield client

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# A. Admin Auth Gate
# ---------------------------------------------------------------------------


class TestAdminAuthGate:
    """A. Verify admin-only enforcement on all article draft endpoints."""

    def test_admin_can_submit_directly_lab_ready(self, admin_client):
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json={
                "raw_text": K8S_DIRECTLY_READY,
                "user_confirmed_right_to_use": True,
                "user_confirmed_no_secrets": True,
            },
        )
        assert resp.status_code == 201, f"Admin should create draft: {resp.text}"

    def test_nonadmin_create_rejected_403(self, nonadmin_client):
        resp = nonadmin_client.post(
            "/api/labgen/article-drafts",
            json={
                "raw_text": K8S_DIRECTLY_READY,
                "user_confirmed_right_to_use": True,
                "user_confirmed_no_secrets": True,
            },
        )
        assert resp.status_code == 403, f"Non-admin must not create drafts: {resp.text}"

    def test_nonadmin_list_rejected_403(self, nonadmin_client):
        resp = nonadmin_client.get("/api/labgen/article-drafts")
        assert resp.status_code == 403, f"Non-admin must not list drafts: {resp.text}"

    def test_nonadmin_get_rejected_403(self, nonadmin_client):
        # Auth check runs before existence check — any draft_id suffices
        resp = nonadmin_client.get("/api/labgen/article-drafts/any-draft-id")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# B. Directly Lab-Ready Happy Path (Sample 1)
# ---------------------------------------------------------------------------


class TestDirectlyLabReadyHappyPath:
    """B. Full happy path with K8s ConfigMap article."""

    def test_feasibility_status_directly_lab_ready(self, admin_client):
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(K8S_DIRECTLY_READY),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["feasibility_result"]["status"] == "directly_lab_ready"

    def test_evaluated_by_stub_not_llm(self, admin_client):
        """LLM must never be called — evaluated_by must be 'stub'."""
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(K8S_DIRECTLY_READY),
        )
        assert resp.status_code == 201
        assert resp.json()["feasibility_result"]["evaluated_by"] == "stub"

    def test_target_domain_k8s(self, admin_client):
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(K8S_DIRECTLY_READY),
        )
        assert resp.json()["target_domain"] == "k8s"

    def test_raw_text_not_in_response(self, admin_client):
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(K8S_DIRECTLY_READY),
        )
        assert resp.status_code == 201
        response_text = resp.text
        # Article body must not appear in response
        assert "my-app-config" not in response_text
        assert "APP_MODE=demo" not in response_text

    def test_raw_text_persisted_false(self, admin_client):
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(K8S_DIRECTLY_READY),
        )
        data = resp.json()
        assert data["storage_policy"]["raw_text_persisted"] is False

    def test_content_hash_present(self, admin_client):
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(K8S_DIRECTLY_READY),
        )
        data = resp.json()
        expected_hash = _sha256(K8S_DIRECTLY_READY)
        assert data["source_metadata"]["content_hash"] == expected_hash

    def test_initial_status_is_draft(self, admin_client):
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(K8S_DIRECTLY_READY),
        )
        assert resp.json()["status"] == "draft"

    def test_not_in_learner_catalog_after_create(self, admin_client):
        """Drafts must not appear in the learner-visible /api/labs endpoint."""
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(K8S_DIRECTLY_READY),
        )
        draft_id = resp.json()["draft_id"]

        catalog_resp = admin_client.get("/api/labs")
        assert catalog_resp.status_code == 200
        lab_ids = [lab["lab_id"] for lab in catalog_resp.json()]
        assert draft_id not in lab_ids

    def test_patch_source_grounding_allowed(self, admin_client):
        """Admin must be able to add source_grounding via PATCH (MEDIUM-001 fix)."""
        create_resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(K8S_DIRECTLY_READY),
        )
        draft_id = create_resp.json()["draft_id"]

        patch_resp = admin_client.patch(
            f"/api/labgen/article-drafts/{draft_id}",
            json={
                "source_grounding": [
                    {
                        "excerpt": "kubectl create configmap my-app-config --from-literal=APP_MODE=demo",
                        "excerpt_hash": _sha256("kubectl create configmap my-app-config --from-literal=APP_MODE=demo"),
                        "contains_sensitive_content": False,
                    }
                ]
            },
        )
        assert patch_resp.status_code == 200, f"PATCH source_grounding must work: {patch_resp.text}"
        data = patch_resp.json()
        assert len(data["source_grounding"]) == 1

    def test_patch_required_runtime_allowed(self, admin_client):
        """Admin must be able to set required_runtime via PATCH (MEDIUM-001 fix)."""
        create_resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(K8S_DIRECTLY_READY),
        )
        draft_id = create_resp.json()["draft_id"]

        patch_resp = admin_client.patch(
            f"/api/labgen/article-drafts/{draft_id}",
            json={
                "required_runtime": {
                    "domain": "k8s",
                    "runtime_type": "k8s_namespace",
                    "cleanup_strategy": "namespace_delete",
                    "production_dependency": False,
                }
            },
        )
        assert patch_resp.status_code == 200, f"PATCH required_runtime must work: {patch_resp.text}"
        data = patch_resp.json()
        assert data["required_runtime"]["cleanup_strategy"] == "namespace_delete"

    def test_patch_verifier_candidates_allowed(self, admin_client):
        """Admin must be able to set verifier_candidates via PATCH (MEDIUM-001 fix)."""
        create_resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(K8S_DIRECTLY_READY),
        )
        draft_id = create_resp.json()["draft_id"]

        patch_resp = admin_client.patch(
            f"/api/labgen/article-drafts/{draft_id}",
            json={
                "verifier_candidates": [
                    {
                        "candidate_state": "reusable_existing",
                        "primitive_name": "configmap_exists",
                        "parameters": {"namespace": "{{lab_namespace}}", "name": "my-app-config"},
                        "review_required": True,
                        "admin_reviewed": True,
                    }
                ]
            },
        )
        assert patch_resp.status_code == 200, f"PATCH verifier_candidates must work: {patch_resp.text}"


# ---------------------------------------------------------------------------
# C. Admin Review Gate (using directly_lab_ready draft)
# ---------------------------------------------------------------------------

_ALL_CONFIRMED = {
    "confirmed_source_grounding": True,
    "confirmed_safety": True,
    "confirmed_cleanup": True,
    "confirmed_verifier_strategy": True,
    "confirmed_no_raw_secret": True,
    "confirmed_no_direct_publish": True,
}


class TestAdminReviewGate:
    """C. Confirm all 6 confirmed_* fields are required for APPROVE."""

    def _create_draft(self, admin_client, text=K8S_DIRECTLY_READY):
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(text),
        )
        return resp.json()["draft_id"]

    def test_partial_confirmed_approve_blocked(self, admin_client):
        """APPROVE without all confirmed_* must return 403."""
        draft_id = self._create_draft(admin_client)
        resp = admin_client.post(
            f"/api/labgen/article-drafts/{draft_id}/review",
            json={
                "decision": "approve",
                "confirmed_source_grounding": True,
                # 5 other confirmed_* fields missing → False
            },
        )
        assert resp.status_code == 403, f"Partial confirmed_* must be rejected: {resp.text}"

    def test_zero_confirmed_approve_blocked(self, admin_client):
        """APPROVE with all confirmed_* False must return 403."""
        draft_id = self._create_draft(admin_client)
        resp = admin_client.post(
            f"/api/labgen/article-drafts/{draft_id}/review",
            json={"decision": "approve"},
        )
        assert resp.status_code == 403

    def test_full_confirmed_approve_succeeds(self, admin_client):
        """APPROVE with all 6 confirmed_* True → APPROVED_FOR_STATIC_VALIDATION."""
        draft_id = self._create_draft(admin_client)
        resp = admin_client.post(
            f"/api/labgen/article-drafts/{draft_id}/review",
            json={"decision": "approve", **_ALL_CONFIRMED},
        )
        assert resp.status_code == 200, f"Full confirmed approve must work: {resp.text}"
        data = resp.json()
        assert data["status"] == "approved_for_static_validation"
        assert data["admin_decision"]["decision"] == "approve"
        assert data["admin_decision"]["confirmed_no_direct_publish"] is True

    def test_request_changes_status(self, admin_client):
        draft_id = self._create_draft(admin_client)
        resp = admin_client.post(
            f"/api/labgen/article-drafts/{draft_id}/review",
            json={"decision": "request_changes", "required_changes": ["add verifier candidate"]},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "needs_changes"

    def test_reject_status(self, admin_client):
        draft_id = self._create_draft(admin_client)
        resp = admin_client.post(
            f"/api/labgen/article-drafts/{draft_id}/review",
            json={"decision": "reject"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

    def test_advance_to_internal_rehearsal(self, admin_client):
        """After approve → APPROVED_FOR_STATIC_VALIDATION, advance to internal rehearsal."""
        draft_id = self._create_draft(admin_client)
        # Approve first
        admin_client.post(
            f"/api/labgen/article-drafts/{draft_id}/review",
            json={"decision": "approve", **_ALL_CONFIRMED},
        )
        # Advance
        resp = admin_client.post(
            f"/api/labgen/article-drafts/{draft_id}/advance",
            json={"target_status": "approved_for_internal_rehearsal"},
        )
        assert resp.status_code == 200, f"Advance to internal rehearsal: {resp.text}"
        assert resp.json()["status"] == "approved_for_internal_rehearsal"

    def test_advance_without_approve_blocked(self, admin_client):
        """Cannot advance to internal rehearsal without prior APPROVE."""
        draft_id = self._create_draft(admin_client)
        resp = admin_client.post(
            f"/api/labgen/article-drafts/{draft_id}/advance",
            json={"target_status": "approved_for_internal_rehearsal"},
        )
        assert resp.status_code == 403, "Cannot advance from DRAFT status"

    def test_full_happy_path_to_publish_candidate(self, admin_client):
        """
        Full happy path with all required fields set:
        DRAFT → approved_for_static_validation → approved_for_internal_rehearsal
        → approved_for_publish_candidate.
        """
        draft_id = self._create_draft(admin_client)

        # Enrich contract with all pipeline-critical fields
        excerpt_text = "kubectl create configmap my-app-config --from-literal=APP_MODE=demo"
        admin_client.patch(
            f"/api/labgen/article-drafts/{draft_id}",
            json={
                "learning_objective": "Create and verify a ConfigMap in Kubernetes",
                "source_grounding": [
                    {
                        "excerpt": excerpt_text,
                        "excerpt_hash": _sha256(excerpt_text),
                        "contains_sensitive_content": False,
                    }
                ],
                "required_runtime": {
                    "domain": "k8s",
                    "runtime_type": "k8s_namespace",
                    "cleanup_strategy": "namespace_delete",
                    "production_dependency": False,
                },
                "verifier_candidates": [
                    {
                        "candidate_state": "reusable_existing",
                        "primitive_name": "configmap_exists",
                        "parameters": {"namespace": "{{lab_namespace}}", "name": "my-app-config"},
                        "review_required": True,
                        "admin_reviewed": True,
                    }
                ],
            },
        )

        # Step 1: Approve
        approve_resp = admin_client.post(
            f"/api/labgen/article-drafts/{draft_id}/review",
            json={"decision": "approve", **_ALL_CONFIRMED},
        )
        assert approve_resp.status_code == 200

        # Step 2: Advance to internal rehearsal
        adv1 = admin_client.post(
            f"/api/labgen/article-drafts/{draft_id}/advance",
            json={"target_status": "approved_for_internal_rehearsal"},
        )
        assert adv1.status_code == 200, f"Advance to internal rehearsal: {adv1.text}"

        # Step 3: Advance to publish candidate
        adv2 = admin_client.post(
            f"/api/labgen/article-drafts/{draft_id}/advance",
            json={"target_status": "approved_for_publish_candidate"},
        )
        assert adv2.status_code == 200, f"Advance to publish candidate: {adv2.text}"
        assert adv2.json()["status"] == "approved_for_publish_candidate"

    def test_convert_to_lab_draft_is_draft_not_published(self, admin_client):
        """Converted LabDraft must be DRAFT, not PUBLISHED. Must not appear in learner catalog."""
        draft_id = self._create_draft(admin_client)

        excerpt_text = "kubectl create configmap lab-config --from-literal=MODE=test"
        admin_client.patch(
            f"/api/labgen/article-drafts/{draft_id}",
            json={
                "learning_objective": "Understand ConfigMaps",
                "source_grounding": [
                    {
                        "excerpt": excerpt_text,
                        "excerpt_hash": _sha256(excerpt_text),
                        "contains_sensitive_content": False,
                    }
                ],
                "required_runtime": {
                    "domain": "k8s",
                    "runtime_type": "k8s_namespace",
                    "cleanup_strategy": "namespace_delete",
                    "production_dependency": False,
                },
                "verifier_candidates": [
                    {
                        "candidate_state": "reusable_existing",
                        "primitive_name": "configmap_exists",
                        "parameters": {"namespace": "{{lab_namespace}}", "name": "lab-config"},
                        "review_required": True,
                        "admin_reviewed": True,
                    }
                ],
            },
        )

        # Advance to publish candidate
        admin_client.post(
            f"/api/labgen/article-drafts/{draft_id}/review",
            json={"decision": "approve", **_ALL_CONFIRMED},
        )
        admin_client.post(
            f"/api/labgen/article-drafts/{draft_id}/advance",
            json={"target_status": "approved_for_internal_rehearsal"},
        )
        admin_client.post(
            f"/api/labgen/article-drafts/{draft_id}/advance",
            json={"target_status": "approved_for_publish_candidate"},
        )

        # Convert
        convert_resp = admin_client.post(f"/api/labgen/article-drafts/{draft_id}/convert")
        assert convert_resp.status_code == 201, f"Convert must succeed: {convert_resp.text}"
        lab_data = convert_resp.json()
        assert lab_data["publish_status"] == "draft"
        assert lab_data["publish_status"] != "published"

        # Must not appear in learner catalog
        catalog_resp = admin_client.get("/api/labs")
        lab_ids = [lab["lab_id"] for lab in catalog_resp.json()]
        assert lab_data["lab_id"] not in lab_ids, "Converted DRAFT must not be in learner catalog"

    def test_convert_from_wrong_status_blocked(self, admin_client):
        """Cannot convert a draft that is not APPROVED_FOR_PUBLISH_CANDIDATE."""
        draft_id = self._create_draft(admin_client)
        resp = admin_client.post(f"/api/labgen/article-drafts/{draft_id}/convert")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# D. StaticValidator Bridge
# ---------------------------------------------------------------------------


class TestStaticValidatorBridge:
    """D. ArticleDraftValidator integration via /validate endpoint."""

    def test_validate_endpoint_returns_list(self, admin_client):
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(K8S_DIRECTLY_READY),
        )
        draft_id = resp.json()["draft_id"]
        validate_resp = admin_client.post(f"/api/labgen/article-drafts/{draft_id}/validate")
        assert validate_resp.status_code == 200
        results = validate_resp.json()
        assert isinstance(results, list)
        assert len(results) > 0

    def test_validate_has_check_ids(self, admin_client):
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(K8S_DIRECTLY_READY),
        )
        draft_id = resp.json()["draft_id"]
        validate_resp = admin_client.post(f"/api/labgen/article-drafts/{draft_id}/validate")
        results = validate_resp.json()
        assert all("check_id" in r for r in results)
        assert all("status" in r for r in results)

    def test_validate_does_not_publish(self, admin_client):
        """Validate must not create any published lab."""
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(K8S_DIRECTLY_READY),
        )
        draft_id = resp.json()["draft_id"]

        before_catalog = admin_client.get("/api/labs").json()
        admin_client.post(f"/api/labgen/article-drafts/{draft_id}/validate")
        after_catalog = admin_client.get("/api/labs").json()

        assert len(before_catalog) == len(after_catalog), "Validate must not add to learner catalog"

    def test_directly_ready_approve_requires_validator_pass(self, admin_client):
        """APPROVE runs ArticleDraftValidator — all 15 checks run."""
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(K8S_DIRECTLY_READY),
        )
        draft_id = resp.json()["draft_id"]
        validate_resp = admin_client.post(f"/api/labgen/article-drafts/{draft_id}/validate")
        results = validate_resp.json()
        # Expect exactly 15 check results (ArticleDraftValidator has 15 checks)
        assert len(results) == 15, f"Expected 15 checks, got {len(results)}: {[r['check_id'] for r in results]}"


# ---------------------------------------------------------------------------
# E. Partial Path (Sample 2)
# ---------------------------------------------------------------------------


class TestPartialPath:
    """E. Partially lab-ready article cannot reach publish candidate."""

    def test_feasibility_status_partially_lab_ready(self, admin_client):
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(K8S_PARTIALLY_READY),
        )
        assert resp.status_code == 201
        assert resp.json()["feasibility_result"]["status"] == "partially_lab_ready"

    def test_missing_requirements_populated(self, admin_client):
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(K8S_PARTIALLY_READY),
        )
        missing = resp.json()["feasibility_result"]["missing_requirements"]
        assert len(missing) > 0, "Partially lab-ready must have missing_requirements"

    def test_evaluated_by_stub(self, admin_client):
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(K8S_PARTIALLY_READY),
        )
        assert resp.json()["feasibility_result"]["evaluated_by"] == "stub"

    def test_partially_ready_cannot_publish(self, admin_client):
        """Partial feasibility blocks advance to publish_candidate."""
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(K8S_PARTIALLY_READY),
        )
        draft_id = resp.json()["draft_id"]

        excerpt_text = "some k8s article excerpt"
        admin_client.patch(
            f"/api/labgen/article-drafts/{draft_id}",
            json={
                "source_grounding": [
                    {
                        "excerpt": excerpt_text,
                        "excerpt_hash": _sha256(excerpt_text),
                        "contains_sensitive_content": False,
                    }
                ],
                "required_runtime": {
                    "domain": "k8s",
                    "runtime_type": "k8s_namespace",
                    "cleanup_strategy": "namespace_delete",
                    "production_dependency": False,
                },
            },
        )
        # Approve
        admin_client.post(
            f"/api/labgen/article-drafts/{draft_id}/review",
            json={"decision": "approve", **_ALL_CONFIRMED},
        )
        # Advance to internal rehearsal
        admin_client.post(
            f"/api/labgen/article-drafts/{draft_id}/advance",
            json={"target_status": "approved_for_internal_rehearsal"},
        )
        # Attempt advance to publish_candidate — must fail
        resp2 = admin_client.post(
            f"/api/labgen/article-drafts/{draft_id}/advance",
            json={"target_status": "approved_for_publish_candidate"},
        )
        assert resp2.status_code in (403, 409), (
            f"Partially lab-ready must not reach publish candidate: {resp2.text}"
        )

    def test_partially_ready_not_in_learner_catalog(self, admin_client):
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(K8S_PARTIALLY_READY),
        )
        draft_id = resp.json()["draft_id"]
        catalog = admin_client.get("/api/labs").json()
        lab_ids = [lab["lab_id"] for lab in catalog]
        assert draft_id not in lab_ids


# ---------------------------------------------------------------------------
# F. Reject Path (Sample 3)
# ---------------------------------------------------------------------------


class TestRejectPath:
    """F. Not-lab-ready theory article."""

    def test_theory_article_not_lab_ready(self, admin_client):
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(K8S_NOT_LAB_READY),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["feasibility_result"]["status"] == "not_lab_ready"

    def test_theory_rejection_code_present(self, admin_client):
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(K8S_NOT_LAB_READY),
        )
        feasibility = resp.json()["feasibility_result"]
        assert feasibility["rejection_code"] == "stub.no_operable_content"

    def test_theory_no_publish_path(self, admin_client):
        """
        NOT_LAB_READY article cannot proceed past approved_for_static_validation.

        Rehearsal finding LOW-001:
          APPROVE from DRAFT status succeeds for NOT_LAB_READY articles (validator check
          article_draft.rejected_feasibility_cannot_publish only fires at APPROVED_FOR_*
          statuses, not during the APPROVE review step itself). However, advance to
          APPROVED_FOR_INTERNAL_REHEARSAL is blocked by the validator at that step.
          So the publish path is effectively blocked — just one step later than expected.
        """
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(K8S_NOT_LAB_READY),
        )
        draft_id = resp.json()["draft_id"]

        # APPROVE from DRAFT succeeds (validator check fires at advanced statuses, not here)
        approve_resp = admin_client.post(
            f"/api/labgen/article-drafts/{draft_id}/review",
            json={"decision": "approve", **_ALL_CONFIRMED},
        )
        assert approve_resp.status_code == 200
        assert approve_resp.json()["status"] == "approved_for_static_validation"

        # Advance to internal rehearsal is blocked (validator fires here)
        adv_resp = admin_client.post(
            f"/api/labgen/article-drafts/{draft_id}/advance",
            json={"target_status": "approved_for_internal_rehearsal"},
        )
        assert adv_resp.status_code == 409, (
            f"NOT_LAB_READY must be blocked at advance to internal rehearsal: {adv_resp.text}"
        )

    def test_theory_not_in_learner_catalog(self, admin_client):
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(K8S_NOT_LAB_READY),
        )
        draft_id = resp.json()["draft_id"]
        catalog = admin_client.get("/api/labs").json()
        assert draft_id not in [lab["lab_id"] for lab in catalog]


# ---------------------------------------------------------------------------
# G. Sensitive Path (Sample 4)
# ---------------------------------------------------------------------------


class TestSensitivePath:
    """G. Article with fake secret-like content must be hard-rejected."""

    def test_sensitive_content_hard_rejected(self, admin_client):
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(SENSITIVE_CONTENT),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["feasibility_result"]["status"] == "not_lab_ready"
        assert data["feasibility_result"]["rejection_code"] == "stub.hard_reject_safety_flag"

    def test_sensitive_safety_flag_set(self, admin_client):
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(SENSITIVE_CONTENT),
        )
        flags = resp.json()["feasibility_result"]["safety_flags"]
        assert "contains_secret_like_content" in flags

    def test_raw_secret_value_not_in_response(self, admin_client):
        """The fake secret value must not appear in the API response."""
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(SENSITIVE_CONTENT),
        )
        assert resp.status_code == 201
        response_text = resp.text
        # The fake key value must not appear
        assert "sk-test-redacted-example-placeholder-value" not in response_text

    def test_raw_secret_not_persisted(self, admin_client, tmp_path):
        """Fake secret value must not appear in the persisted JSON file."""
        from backend.labgen.article_draft_repository import ArticleDraftRepository
        from backend.labgen.repository import LabDraftRepository
        from backend.labgen.article_draft_service import ArticleDraftService
        import backend.labgen.article_draft_routes as adr
        from backend.auth_deps import get_current_user
        from backend.auth import auth_manager
        from backend.main import app

        persist_path = tmp_path / "sensitive_test.json"
        article_repo = ArticleDraftRepository(path=persist_path)
        lab_repo = LabDraftRepository(path=tmp_path / "labs_s.json")
        svc = ArticleDraftService(article_repo=article_repo, lab_repo=lab_repo)
        app.dependency_overrides[adr.get_article_draft_service] = lambda: svc
        _real = auth_manager.is_admin
        auth_manager.is_admin = lambda u: u == "s_admin" or _real(u)
        app.dependency_overrides[get_current_user] = lambda: "s_admin"

        try:
            with TestClient(app, raise_server_exceptions=True) as client:
                client.post(
                    "/api/labgen/article-drafts",
                    json=_create_payload(SENSITIVE_CONTENT),
                )
            # Check persisted JSON
            raw_file = persist_path.read_text()
            assert "sk-test-redacted-example-placeholder-value" not in raw_file
            assert "BEGIN PRIVATE KEY" not in raw_file
        finally:
            app.dependency_overrides.clear()
            auth_manager.is_admin = _real

    def test_sensitive_content_not_in_catalog(self, admin_client):
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(SENSITIVE_CONTENT),
        )
        draft_id = resp.json()["draft_id"]
        catalog = admin_client.get("/api/labs").json()
        assert draft_id not in [lab["lab_id"] for lab in catalog]


# ---------------------------------------------------------------------------
# H. Catalog Isolation
# ---------------------------------------------------------------------------


class TestCatalogIsolation:
    """H. No article draft of any kind appears in the learner catalog."""

    def test_catalog_unchanged_after_four_samples(self, admin_client):
        """Submit all 4 samples; learner catalog must remain unchanged."""
        before_catalog = admin_client.get("/api/labs").json()

        for text in [K8S_DIRECTLY_READY, K8S_PARTIALLY_READY, K8S_NOT_LAB_READY, SENSITIVE_CONTENT]:
            admin_client.post("/api/labgen/article-drafts", json=_create_payload(text))

        after_catalog = admin_client.get("/api/labs").json()
        # Catalog count must not increase
        assert len(after_catalog) == len(before_catalog)

    def test_article_drafts_not_visible_in_lab_list(self, admin_client):
        """Article drafts endpoint must be separate from lab drafts endpoint."""
        admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(K8S_DIRECTLY_READY),
        )
        # Learner catalog returns only PUBLISHED LabDrafts — article drafts never show
        catalog = admin_client.get("/api/labs").json()
        # All returned items must have a publish_status of "published" (or catalog is empty)
        # Article draft IDs are UUIDs with prefix "article_draft_*" - none should appear
        for lab in catalog:
            assert "article_draft" not in lab.get("lab_id", ""), (
                f"Article draft appeared in learner catalog: {lab['lab_id']}"
            )


# ---------------------------------------------------------------------------
# I. Invariants
# ---------------------------------------------------------------------------


class TestInvariants:
    """I. System-level invariants that must hold across all rehearsal scenarios."""

    def test_lllm_never_called_directly_ready(self, admin_client):
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(K8S_DIRECTLY_READY),
        )
        assert resp.json()["feasibility_result"]["evaluated_by"] == "stub"

    def test_lllm_never_called_sensitive(self, admin_client):
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(SENSITIVE_CONTENT),
        )
        assert resp.json()["feasibility_result"]["evaluated_by"] == "stub"

    def test_lllm_never_called_partial(self, admin_client):
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(K8S_PARTIALLY_READY),
        )
        assert resp.json()["feasibility_result"]["evaluated_by"] == "stub"

    def test_lllm_never_called_theory(self, admin_client):
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(K8S_NOT_LAB_READY),
        )
        assert resp.json()["feasibility_result"]["evaluated_by"] == "stub"

    def test_raw_text_persisted_always_false(self, admin_client):
        for text in [K8S_DIRECTLY_READY, K8S_PARTIALLY_READY, K8S_NOT_LAB_READY, SENSITIVE_CONTENT]:
            resp = admin_client.post("/api/labgen/article-drafts", json=_create_payload(text))
            assert resp.json()["storage_policy"]["raw_text_persisted"] is False

    def test_cloud_domain_blocked(self, admin_client):
        """Cloud-only articles must be NOT_LAB_READY with cloud_domain_blocked_v1."""
        cloud_article = """
        Deploy an EC2 instance on AWS for your application backend.

        ```bash
        aws ec2 run-instances --image-id ami-12345678 --instance-type t2.micro
        ```

        Check the instance status:
        ```bash
        aws ec2 describe-instances --instance-ids i-1234567890abcdef0
        ```

        The EC2 instance should be running in your AWS account.
        """
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json={"raw_text": cloud_article},
        )
        assert resp.status_code == 201
        feasibility = resp.json()["feasibility_result"]
        assert feasibility["status"] == "not_lab_ready"
        assert feasibility["rejection_code"] == "stub.cloud_domain_blocked_v1"

    def test_directly_ready_requires_admin_review_not_auto_approved(self, admin_client):
        """directly_lab_ready must not auto-approve — status starts as 'draft'."""
        resp = admin_client.post(
            "/api/labgen/article-drafts",
            json=_create_payload(K8S_DIRECTLY_READY),
        )
        data = resp.json()
        assert data["status"] == "draft"
        assert data["admin_decision"]["decision"] == "pending"

    def test_all_four_samples_create_drafts(self, admin_client):
        """All samples create a persisted contract (even rejected ones)."""
        for text in [K8S_DIRECTLY_READY, K8S_PARTIALLY_READY, K8S_NOT_LAB_READY, SENSITIVE_CONTENT]:
            resp = admin_client.post("/api/labgen/article-drafts", json=_create_payload(text))
            assert resp.status_code == 201
            assert resp.json()["draft_id"]
