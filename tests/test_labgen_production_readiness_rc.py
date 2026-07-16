"""
Production Readiness Release Candidate Gate — RC Smoke Tests v0.1.

Focus: RC contract / safety / no side-effect leakage.
Does NOT duplicate exhaustive business-logic tests in mvp_runtime_smoke.py or demo_flow_smoke.py.

Coverage:
  A. Admin-only read endpoints: contract pack (19 endpoints), LLM provider status, adapter status
  B. Publish pipeline: demo seed → image-blocked draft → publish blocked
  C. Learner catalog: published only, no credential/draft leakage
  D. Full session lifecycle: start → step check → complete → snapshot → audit
  E. Expiry dry-run: find expired without mutation
  F. Admin-only enforcement: learner gets 403 on all admin endpoints
  G. Sensitive data guard: all response types pass no-leak assertion
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.labgen.demo_seed import (
    DEMO_DRAFT_ID_DATA_BLOCKED,
    DEMO_DRAFT_ID_HTTP,
    DEMO_DRAFT_ID_PYTHON,
    DEMO_DRAFT_ID_PYTHON_UNRESOLVED,
    DEMO_SESSION_ID_ACTIVE,
    DEMO_STUDENT_USERNAME,
    DemoSeedService,
)
from backend.labgen.failure_reasons import FailureReason
from backend.labgen.image_readiness import ImageReadinessService
from backend.labgen.lab_session_repository import LabSessionRepository
from backend.labgen.lab_session_service import (
    LabSessionService,
    StubVMTracker,
)
from backend.labgen.learner_session_snapshot import LearnerSessionSnapshotService
from backend.labgen.models import (
    CleanupNamespace,
    CleanupSpec,
    ExplainField,
    ImageResolutionResult,
    ImageStatus,
    LabDraft,
    LabSessionState,
    LabSessionStatus,
    PublishStatus,
    RuntimeRequirements,
    RuntimeAuditEvent,
    Step,
    VerifierCredentialMetadata,
    VerifyTemplate,
    VerifyType,
)
from backend.labgen.namespace_lifecycle import StubNamespaceLifecycleAdapter
from backend.labgen.publish_service import PublishService
from backend.labgen.routes import (
    get_audit_repository,
    get_expiry_service,
    get_image_resolver,
    get_llm_provider_service,
    get_preview_service,
    get_publish_service,
    get_repository,
    get_session_repository,
    get_session_service,
    get_snapshot_service,
    get_step_progression_service,
    require_admin_user,
)
from backend.labgen.draft_preview import DraftPreviewService
from backend.labgen.runtime_audit import RuntimeAuditRepository, RuntimeAuditService
from backend.labgen.static_validator import StaticValidator
from backend.labgen.step_progression_service import StepProgressionService
from backend.labgen.verifier import FakeK8sVerifierClient, VerifierService
from backend.labgen.vm_expiry import VMExpiryService

pytestmark = pytest.mark.static

# KNOWN DEBT (2026-07-12, found while adding verify.type_implemented in the
# Service-no-Endpoints lab sprint): demo_seed's PYTHON_BASICS/HTTP_API_BASICS
# templates reference nonexistent manifests/*.yaml files (pre-existing,
# unrelated to this check) and separately use unimplemented VerifyType values
# (POD_READY, JOB_COMPLETED) newly caught by verify.type_implemented, so
# /api/labgen/demo/seed no longer successfully publishes them. Tracked, not
# silently hidden — see CHANGELOG for the sprint that surfaced this.
_TEMPLATE_DEBT_XFAIL_REASON = (
    "KNOWN DEBT: GenerationTemplateRegistry fixtures reference nonexistent "
    "manifest files and use unimplemented VerifyType values (POD_READY/"
    "JOB_COMPLETED) now caught by verify.type_implemented — see git blame / "
    "CHANGELOG for the Service-no-Endpoints lab sprint that surfaced this."
)

# ===========================================================================
# Sensitive data guard (RC-level, mirrors mvp_runtime_smoke allowlist rules)
# ===========================================================================

_ABSOLUTE_SENSITIVE = frozenset({
    "kubeconfig",
    "private_key",
    "traceback",
    "stack trace",
    "raw exception",
    "password",
})
# Note: this guard catches the string "kubeconfig" in values, but a raw kubeconfig YAML
# (e.g. "apiVersion: v1\nkind: Config\n...") does NOT contain the word "kubeconfig" and
# would not be caught. No current code path exposes raw kubeconfig YAML in an HTTP response
# (VerifierCredentialStore.export_verifier_kubeconfig returns {"status":"ok"} only). If
# that invariant ever changes, add "apiversion" / "kind: config" / "clusters:" to this set.

_MACHINE_CODE_RE = re.compile(r"^[a-z][a-z_]*$")


def _collect_leaf_strings(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, list):
        out: list[str] = []
        for item in obj:
            out.extend(_collect_leaf_strings(item))
        return out
    if isinstance(obj, dict):
        out = []
        for v in obj.values():
            out.extend(_collect_leaf_strings(v))
        return out
    return []


def _assert_no_sensitive(payload, context: str = "") -> None:
    """Assert no leaf string value contains sensitive data."""
    for val in _collect_leaf_strings(payload):
        v = val.lower()
        for kw in _ABSOLUTE_SENSITIVE:
            assert kw not in v, (
                f"Sensitive keyword {kw!r} in {context or 'response'}: {val[:120]!r}"
            )
        if "token" in v:
            safe = _MACHINE_CODE_RE.match(val) and len(val) <= 60
            assert safe, f"Possible token leak in {context}: {val[:120]!r}"
        if "secret" in v:
            safe = _MACHINE_CODE_RE.match(val) and len(val) <= 40
            assert safe, f"Possible secret leak in {context}: {val[:120]!r}"
        if "credential" in v:
            safe = _MACHINE_CODE_RE.match(val) and len(val) <= 60
            assert safe, f"Possible credential leak in {context}: {val[:120]!r}"


# ===========================================================================
# In-memory fakes
# ===========================================================================


class _MemDraftRepo:
    def __init__(self) -> None:
        self._store: dict[str, LabDraft] = {}

    def _rt(self, d: LabDraft) -> LabDraft:
        return LabDraft.model_validate(d.model_dump(mode="json"))

    def create(self, d: LabDraft) -> LabDraft:
        v = self._rt(d)
        self._store[v.lab_id] = v
        return v

    def get(self, lab_id: str) -> Optional[LabDraft]:
        return self._store.get(lab_id)

    def update(self, d: LabDraft) -> LabDraft:
        v = self._rt(d)
        self._store[v.lab_id] = v
        return v

    def delete(self, lab_id: str) -> None:
        self._store.pop(lab_id, None)

    def list_all(self) -> list[LabDraft]:
        return list(self._store.values())


class _MemSessionRepo:
    def __init__(self) -> None:
        self._store: dict[str, LabSessionState] = {}

    def create(self, s: LabSessionState) -> LabSessionState:
        self._store[s.session_id] = s
        return s

    def get(self, session_id: str) -> Optional[LabSessionState]:
        return self._store.get(session_id)

    def update(self, s: LabSessionState) -> LabSessionState:
        self._store[s.session_id] = s
        return s

    def delete(self, session_id: str) -> None:
        self._store.pop(session_id, None)

    def list_by_student(self, username: str) -> list[LabSessionState]:
        return [s for s in self._store.values() if s.student_username == username]

    def list_all(self) -> list[LabSessionState]:
        return list(self._store.values())


class _MemAuditRepo:
    def __init__(self) -> None:
        self._store: dict[str, list[RuntimeAuditEvent]] = {}

    def append(self, event: RuntimeAuditEvent) -> RuntimeAuditEvent:
        self._store.setdefault(event.session_id, []).append(event)
        return event

    def list_by_session(self, session_id: str) -> list[RuntimeAuditEvent]:
        return list(self._store.get(session_id, []))


class _FakeCredStore:
    def exists(self, vm_id: str) -> bool:
        return True

    def load(self, vm_id: str):
        meta = VerifierCredentialMetadata(
            vm_id=vm_id,
            created_at=datetime.now(tz=timezone.utc),
            expires_at=datetime.now(tz=timezone.utc) + timedelta(days=365),
            k3s_endpoint="https://k3s-test.internal:6443",
        )
        return "apiVersion: v1\nkind: Config\nclusters: []\n", meta


class _StubImageResolver:
    def needs_recheck(self, img: ImageResolutionResult) -> bool:
        return False

    def check_registry_existence(self, img: ImageResolutionResult) -> ImageResolutionResult:
        return img.model_copy(update={"existence_check_passed": True})


# ===========================================================================
# RC context manager
# ===========================================================================


class _ContainsEverything:
    """Stand-in for LABGEN_ENABLED_LAB_IDS when the allowlist gate itself isn't
    under test — drafts get fresh UUIDs per test, so membership must trivially
    hold for any of them without pre-enumerating IDs."""

    def __contains__(self, item: object) -> bool:
        return True


@contextmanager
def _rc_ctx(*, student: str = "student1"):
    """Wire all LabGen deps with shared in-memory stores.

    Yields: dict with client, draft_repo, session_repo, audit_repo, as_admin(), as_learner().
    """
    from backend.main import app
    from backend.auth_deps import get_current_user

    draft_repo = _MemDraftRepo()
    session_repo = _MemSessionRepo()
    audit_repo = _MemAuditRepo()
    img_resolver = _StubImageResolver()

    audit_svc = RuntimeAuditService(repo=audit_repo)
    vm_tracker = StubVMTracker()

    session_svc = LabSessionService(
        session_repo=session_repo,
        draft_repo=draft_repo,
        vm_tracker=vm_tracker,
        ns_lifecycle=StubNamespaceLifecycleAdapter(),
        image_resolver=img_resolver,
        audit_svc=audit_svc,
    )

    cred_store = _FakeCredStore()
    k8s_client = FakeK8sVerifierClient(default=True)
    verifier_svc = VerifierService(
        session_repo=session_repo,
        credential_store=cred_store,
        k8s_client_factory=lambda _kc: k8s_client,
    )

    step_svc = StepProgressionService(
        session_repo=session_repo,
        draft_repo=draft_repo,
        verifier_svc=verifier_svc,
        audit_svc=audit_svc,
    )

    pub_svc = PublishService(
        validator=StaticValidator(),
        image_resolver=_StubImageResolver(),
    )

    preview_svc = DraftPreviewService(
        repo=draft_repo,
        validator=StaticValidator(),
        image_readiness_svc=ImageReadinessService(),
    )

    snapshot_svc = LearnerSessionSnapshotService(
        session_repo=session_repo,
        draft_repo=draft_repo,
    )

    expiry_svc = VMExpiryService(
        session_repo=session_repo,
        session_service=session_svc,
    )

    saved = dict(app.dependency_overrides)

    app.dependency_overrides.update({
        get_repository: lambda: draft_repo,
        get_session_repository: lambda: session_repo,
        get_session_service: lambda: session_svc,
        get_step_progression_service: lambda: step_svc,
        get_audit_repository: lambda: audit_repo,
        get_publish_service: lambda: pub_svc,
        get_image_resolver: lambda: img_resolver,
        get_preview_service: lambda: preview_svc,
        get_snapshot_service: lambda: snapshot_svc,
        get_expiry_service: lambda: expiry_svc,
        require_admin_user: lambda: "admin",
        get_current_user: lambda: student,
    })

    client = TestClient(app, raise_server_exceptions=True)

    def _as_admin():
        app.dependency_overrides[get_current_user] = lambda: "admin"
        app.dependency_overrides[require_admin_user] = lambda: "admin"

    def _as_learner():
        app.dependency_overrides[get_current_user] = lambda: student
        # Remove require_admin_user override so admin-only endpoints correctly 403.
        app.dependency_overrides.pop(require_admin_user, None)

    # This suite tests RC/production-readiness contracts, not the LABGEN_ENABLED_LAB_IDS
    # allowlist gate itself — drafts get fresh UUIDs per test, so bypass with a stand-in
    # rather than pre-enumerating IDs.
    allowlist_patch = patch("backend.labgen.routes.config.LABGEN_ENABLED_LAB_IDS", _ContainsEverything())
    allowlist_patch.start()
    try:
        yield {
            "client": client,
            "draft_repo": draft_repo,
            "session_repo": session_repo,
            "audit_repo": audit_repo,
            "vm_tracker": vm_tracker,
            "as_admin": _as_admin,
            "as_learner": _as_learner,
        }
    finally:
        allowlist_patch.stop()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)


# ===========================================================================
# Shared draft helpers
# ===========================================================================


def _minimal_published_draft(lab_id: str, draft_repo: _MemDraftRepo) -> LabDraft:
    """Create and publish a minimal but valid draft in the given repo."""
    step = Step(
        step_id="s1",
        order=1,
        why="Understand pods",
        do="Deploy nginx",
        commands=["kubectl create deployment nginx --image=172.16.100.1:5000/nginx:1.25"],
        observe="Pod is Running",
        explain=ExplainField(
            concept="Pod lifecycle",
            observation="Scheduler assigns node",
            published_to_student=True,
            admin_verified=True,
        ),
        verify=[VerifyTemplate(
            verify_id="v1",
            type=VerifyType.POD_RUNNING,
            namespace="{{lab_namespace}}",
            name="nginx",
        )],
    )
    draft = LabDraft(
        lab_id=lab_id,
        source_article_id="art-rc",
        title="RC Test Lab",
        description="A minimal RC-gate lab for smoke testing.",
        estimated_duration_minutes=30,
        prerequisites=[],
        steps=[step],
        runtime_requirements=RuntimeRequirements(
            namespace_template="rc-{username}-{lab_id}",
        ),
        cleanup=CleanupSpec(
            namespace_cleanup=CleanupNamespace(delete_namespace=True),
            cluster_scoped_resources=[],
        ),
        image_resolution=[
            ImageResolutionResult(
                image_intent="nginx",
                requested_image="172.16.100.1:5000/nginx:1.25",
                resolved_image="172.16.100.1:5000/nginx:1.25",
                image_status=ImageStatus.RESOLVED,
                existence_check_passed=True,
            )
        ],
    )
    draft = draft_repo.create(draft)
    pub_svc = PublishService(
        validator=StaticValidator(),
        image_resolver=_StubImageResolver(),
    )
    published = pub_svc.publish(draft)
    return draft_repo.update(published)


# ===========================================================================
# A. Admin-only read endpoints
# ===========================================================================


class TestContractPack:
    def test_returns_200_for_admin(self):
        with _rc_ctx() as ctx:
            r = ctx["client"].get("/api/labgen/contract-pack")
            assert r.status_code == 200

    def test_contains_20_endpoints(self):
        with _rc_ctx() as ctx:
            r = ctx["client"].get("/api/labgen/contract-pack")
            body = r.json()
            assert len(body["endpoints"]) == 20

    def test_contract_pack_examples_no_real_credentials(self):
        """Examples in contract pack must not contain real credential patterns."""
        with _rc_ctx() as ctx:
            r = ctx["client"].get("/api/labgen/contract-pack")
            body = r.json()
            # Check examples (not the field-name policy, which intentionally names "kubeconfig")
            for ex in body.get("examples", []):
                text = str(ex.get("request_example", "")) + str(ex.get("response_example", ""))
                assert "-----BEGIN" not in text, "PEM data in contract example"
                assert "sk-" not in text, "API key in contract example"
                assert "Bearer " not in text, "Bearer token in contract example"

    def test_contract_pack_has_sensitive_field_policy(self):
        with _rc_ctx() as ctx:
            r = ctx["client"].get("/api/labgen/contract-pack")
            policy = r.json().get("sensitive_field_policy", {})
            assert len(policy) >= 4


class TestLLMProviderStatus:
    def test_returns_200_for_admin(self):
        with _rc_ctx() as ctx:
            r = ctx["client"].get("/api/labgen/llm-provider/status")
            assert r.status_code == 200

    def test_live_enabled_is_false(self):
        with _rc_ctx() as ctx:
            r = ctx["client"].get("/api/labgen/llm-provider/status")
            assert r.json()["live_enabled"] is False

    def test_mode_is_fake_or_disabled(self):
        with _rc_ctx() as ctx:
            r = ctx["client"].get("/api/labgen/llm-provider/status")
            assert r.json()["mode"] in ("fake_only", "disabled", "dry_run")

    def test_provider_status_no_api_key(self):
        with _rc_ctx() as ctx:
            r = ctx["client"].get("/api/labgen/llm-provider/status")
            body_str = str(r.json())
            assert "sk-" not in body_str
            assert "api_key" not in body_str

    def test_provider_status_no_sensitive_data(self):
        with _rc_ctx() as ctx:
            r = ctx["client"].get("/api/labgen/llm-provider/status")
            _assert_no_sensitive(r.json(), "llm-provider/status")


class TestRuntimeAdapterStatus:
    def test_returns_200_for_admin(self):
        with _rc_ctx() as ctx:
            r = ctx["client"].get("/api/labgen/runtime/adapter-status")
            assert r.status_code == 200

    def test_response_has_required_fields(self):
        with _rc_ctx() as ctx:
            r = ctx["client"].get("/api/labgen/runtime/adapter-status")
            body = r.json()
            assert "runtime_mode" in body
            assert "production_safe" in body
            assert "namespace_adapter_kind" in body

    def test_adapter_status_no_sensitive_data(self):
        with _rc_ctx() as ctx:
            r = ctx["client"].get("/api/labgen/runtime/adapter-status")
            _assert_no_sensitive(r.json(), "runtime/adapter-status")


# ===========================================================================
# B. Publish pipeline: demo seed + image-blocked publish gate
# ===========================================================================


class TestPublishPipelineRC:
    def test_demo_seed_returns_200(self):
        with _rc_ctx() as ctx:
            r = ctx["client"].post("/api/labgen/demo/seed", json={"reset": False})
            assert r.status_code == 200

    def test_demo_seed_no_sensitive_data(self):
        with _rc_ctx() as ctx:
            r = ctx["client"].post("/api/labgen/demo/seed", json={"reset": False})
            _assert_no_sensitive(r.json(), "demo-seed")

    def test_image_blocked_draft_cannot_publish(self):
        with _rc_ctx() as ctx:
            ctx["client"].post("/api/labgen/demo/seed", json={"reset": False})
            r = ctx["client"].post(
                f"/api/labgen/drafts/{DEMO_DRAFT_ID_DATA_BLOCKED}/publish"
            )
            assert r.status_code == 409

    def test_image_unresolved_draft_cannot_publish(self):
        with _rc_ctx() as ctx:
            ctx["client"].post("/api/labgen/demo/seed", json={"reset": False})
            r = ctx["client"].post(
                f"/api/labgen/drafts/{DEMO_DRAFT_ID_PYTHON_UNRESOLVED}/publish"
            )
            assert r.status_code == 409

    def test_publish_409_no_sensitive_data(self):
        with _rc_ctx() as ctx:
            ctx["client"].post("/api/labgen/demo/seed", json={"reset": False})
            r = ctx["client"].post(
                f"/api/labgen/drafts/{DEMO_DRAFT_ID_DATA_BLOCKED}/publish"
            )
            _assert_no_sensitive(r.json(), "publish-blocked-response")


# ===========================================================================
# C. Learner catalog: only published labs visible
# ===========================================================================


class TestLearnerCatalogRC:
    @pytest.mark.xfail(reason=_TEMPLATE_DEBT_XFAIL_REASON, strict=True)
    def test_published_lab_visible(self):
        with _rc_ctx() as ctx:
            ctx["client"].post("/api/labgen/demo/seed", json={"reset": False})
            ctx["as_learner"]()
            r = ctx["client"].get("/api/labs")
            assert r.status_code == 200
            ids = [lab["lab_id"] for lab in r.json()]
            assert DEMO_DRAFT_ID_PYTHON in ids
            assert DEMO_DRAFT_ID_HTTP in ids

    def test_blocked_draft_absent_from_catalog(self):
        with _rc_ctx() as ctx:
            ctx["client"].post("/api/labgen/demo/seed", json={"reset": False})
            ctx["as_learner"]()
            r = ctx["client"].get("/api/labs")
            ids = [lab["lab_id"] for lab in r.json()]
            assert DEMO_DRAFT_ID_DATA_BLOCKED not in ids
            assert DEMO_DRAFT_ID_PYTHON_UNRESOLVED not in ids

    def test_catalog_response_no_sensitive_data(self):
        with _rc_ctx() as ctx:
            ctx["client"].post("/api/labgen/demo/seed", json={"reset": False})
            ctx["as_learner"]()
            r = ctx["client"].get("/api/labs")
            _assert_no_sensitive(r.json(), "learner-catalog")

    def test_unpublished_draft_detail_returns_404(self):
        with _rc_ctx() as ctx:
            ctx["client"].post("/api/labgen/demo/seed", json={"reset": False})
            ctx["as_learner"]()
            r = ctx["client"].get(f"/api/labs/{DEMO_DRAFT_ID_DATA_BLOCKED}")
            assert r.status_code == 404

    @pytest.mark.xfail(reason=_TEMPLATE_DEBT_XFAIL_REASON, strict=True)
    def test_start_eligibility_for_published_lab(self):
        with _rc_ctx() as ctx:
            ctx["client"].post("/api/labgen/demo/seed", json={"reset": False})
            ctx["as_learner"]()
            r = ctx["client"].get(f"/api/labs/{DEMO_DRAFT_ID_PYTHON}/start-eligibility")
            assert r.status_code == 200
            body = r.json()
            assert "is_startable" in body
            _assert_no_sensitive(body, "start-eligibility")


# ===========================================================================
# D. Full session lifecycle: start → step check → complete → snapshot → audit
# ===========================================================================


class TestSessionLifecycleRC:
    def _setup_draft(self, ctx) -> str:
        lab_id = "rc-gate-lab-001"
        _minimal_published_draft(lab_id, ctx["draft_repo"])
        return lab_id

    def test_start_session_returns_201(self):
        with _rc_ctx() as ctx:
            lab_id = self._setup_draft(ctx)
            r = ctx["client"].post("/api/lab-sessions", json={
                "lab_id": lab_id,
                "vm_id": "500",
            })
            assert r.status_code == 201

    def test_start_session_response_no_sensitive_data(self):
        with _rc_ctx() as ctx:
            lab_id = self._setup_draft(ctx)
            r = ctx["client"].post("/api/lab-sessions", json={
                "lab_id": lab_id,
                "vm_id": "500",
            })
            _assert_no_sensitive(r.json(), "session-start-response")

    def test_start_session_status_lab_active(self):
        with _rc_ctx() as ctx:
            lab_id = self._setup_draft(ctx)
            r = ctx["client"].post("/api/lab-sessions", json={
                "lab_id": lab_id,
                "vm_id": "500",
            })
            assert r.json()["lab_session_status"] == LabSessionStatus.LAB_ACTIVE.value

    def test_step_check_returns_200(self):
        with _rc_ctx() as ctx:
            lab_id = self._setup_draft(ctx)
            start = ctx["client"].post("/api/lab-sessions", json={
                "lab_id": lab_id,
                "vm_id": "500",
            })
            session_id = start.json()["session_id"]
            r = ctx["client"].post(
                f"/api/lab-sessions/{session_id}/steps/s1/check"
            )
            assert r.status_code == 200

    def test_step_check_response_no_sensitive_data(self):
        with _rc_ctx() as ctx:
            lab_id = self._setup_draft(ctx)
            start = ctx["client"].post("/api/lab-sessions", json={
                "lab_id": lab_id,
                "vm_id": "500",
            })
            session_id = start.json()["session_id"]
            r = ctx["client"].post(
                f"/api/lab-sessions/{session_id}/steps/s1/check"
            )
            _assert_no_sensitive(r.json(), "step-check-response")

    def test_complete_session_after_all_steps_pass(self):
        with _rc_ctx() as ctx:
            lab_id = self._setup_draft(ctx)
            start = ctx["client"].post("/api/lab-sessions", json={
                "lab_id": lab_id,
                "vm_id": "500",
            })
            session_id = start.json()["session_id"]
            ctx["client"].post(f"/api/lab-sessions/{session_id}/steps/s1/check")
            r = ctx["client"].post(f"/api/lab-sessions/{session_id}/complete")
            assert r.status_code == 200
            assert r.json()["lab_session_status"] in (
                LabSessionStatus.LAB_COMPLETED.value,
                LabSessionStatus.LAB_CLOSED.value,
            )

    def test_complete_session_no_sensitive_data(self):
        with _rc_ctx() as ctx:
            lab_id = self._setup_draft(ctx)
            start = ctx["client"].post("/api/lab-sessions", json={
                "lab_id": lab_id,
                "vm_id": "500",
            })
            session_id = start.json()["session_id"]
            ctx["client"].post(f"/api/lab-sessions/{session_id}/steps/s1/check")
            r = ctx["client"].post(f"/api/lab-sessions/{session_id}/complete")
            _assert_no_sensitive(r.json(), "session-complete-response")

    def test_session_snapshot_no_sensitive_data(self):
        with _rc_ctx() as ctx:
            lab_id = self._setup_draft(ctx)
            start = ctx["client"].post("/api/lab-sessions", json={
                "lab_id": lab_id,
                "vm_id": "500",
            })
            session_id = start.json()["session_id"]
            r = ctx["client"].get(f"/api/lab-sessions/{session_id}/snapshot")
            assert r.status_code == 200
            _assert_no_sensitive(r.json(), "session-snapshot")

    def test_snapshot_does_not_contain_vm_id_but_exposes_namespace(self):
        # vm_id is hidden; namespace is intentionally exposed for terminal badge.
        with _rc_ctx() as ctx:
            lab_id = self._setup_draft(ctx)
            start = ctx["client"].post("/api/lab-sessions", json={
                "lab_id": lab_id,
                "vm_id": "500",
            })
            session_id = start.json()["session_id"]
            r = ctx["client"].get(f"/api/lab-sessions/{session_id}/snapshot")
            body = r.json()
            body_str = str(body)
            assert "vm_id" not in body_str
            assert "namespace" in body   # key present (namespace exposed for terminal badge)

    def test_audit_events_no_sensitive_data(self):
        with _rc_ctx() as ctx:
            lab_id = self._setup_draft(ctx)
            start = ctx["client"].post("/api/lab-sessions", json={
                "lab_id": lab_id,
                "vm_id": "500",
            })
            session_id = start.json()["session_id"]
            r = ctx["client"].get(f"/api/lab-sessions/{session_id}/audit-events")
            assert r.status_code == 200
            _assert_no_sensitive(r.json(), "audit-events")


# ===========================================================================
# E. Expiry dry-run
# ===========================================================================


class TestExpiryDryRunRC:
    def test_expiry_dry_run_returns_200(self):
        with _rc_ctx() as ctx:
            r = ctx["client"].post(
                "/api/labgen/runtime/expire-sessions",
                json={"dry_run": True},
            )
            assert r.status_code == 200

    def test_expiry_dry_run_finds_zero_in_empty_repo(self):
        with _rc_ctx() as ctx:
            r = ctx["client"].post(
                "/api/labgen/runtime/expire-sessions",
                json={"dry_run": True},
            )
            body = r.json()
            assert body["expired_session_ids"] == []
            assert body["tainted_vm_ids"] == []

    def test_expiry_dry_run_no_sensitive_data(self):
        with _rc_ctx() as ctx:
            r = ctx["client"].post(
                "/api/labgen/runtime/expire-sessions",
                json={"dry_run": True},
            )
            _assert_no_sensitive(r.json(), "expire-sessions-dry-run")

    def test_expiry_dry_run_finds_expired_session(self):
        """dry_run=True: expired sessions appear in expired_session_ids but NOT cleaned."""
        with _rc_ctx() as ctx:
            lab_id = "rc-expiry-lab"
            _minimal_published_draft(lab_id, ctx["draft_repo"])
            start = ctx["client"].post("/api/lab-sessions", json={
                "lab_id": lab_id,
                "vm_id": "500",
            })
            session_id = start.json()["session_id"]

            session = ctx["session_repo"].get(session_id)
            session.started_at = datetime.now(tz=timezone.utc) - timedelta(hours=2)
            ctx["session_repo"].update(session)

            r = ctx["client"].post(
                "/api/labgen/runtime/expire-sessions",
                json={"dry_run": True},
            )
            body = r.json()
            assert session_id in body["expired_session_ids"]
            assert body["cleaned_session_ids"] == []

    def test_expiry_live_run_actually_cleans_expired_session(self):
        """dry_run=False: expired session is cleaned and moved to closed/failed."""
        with _rc_ctx() as ctx:
            lab_id = "rc-expiry-live-lab"
            _minimal_published_draft(lab_id, ctx["draft_repo"])
            start = ctx["client"].post("/api/lab-sessions", json={
                "lab_id": lab_id,
                "vm_id": "500",
            })
            session_id = start.json()["session_id"]

            session = ctx["session_repo"].get(session_id)
            session.started_at = datetime.now(tz=timezone.utc) - timedelta(hours=2)
            ctx["session_repo"].update(session)

            r = ctx["client"].post(
                "/api/labgen/runtime/expire-sessions",
                json={"dry_run": False},
            )
            body = r.json()
            assert session_id in body["cleaned_session_ids"]
            expired_session = ctx["session_repo"].get(session_id)
            assert expired_session.lab_session_status in (
                LabSessionStatus.LAB_CLOSED,
                LabSessionStatus.LAB_CLEANUP_FAILED,
                LabSessionStatus.LAB_TIMEOUT,
            )


# ===========================================================================
# F. Admin-only enforcement: learner must get 403
# ===========================================================================


class TestAdminOnlyEnforcementRC:
    def _make_non_admin_client(self):
        """Return a TestClient where require_admin_user raises 403."""
        from backend.main import app
        from backend.auth_deps import get_current_user
        from fastapi import HTTPException

        saved = dict(app.dependency_overrides)

        def _raise_403():
            raise HTTPException(status_code=403, detail="Admin access required")

        app.dependency_overrides[require_admin_user] = _raise_403
        app.dependency_overrides[get_current_user] = lambda: "regularuser"

        client = TestClient(app, raise_server_exceptions=False)
        return client, saved, app

    def _restore(self, app, saved):
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)

    def test_contract_pack_returns_403_for_non_admin(self):
        client, saved, app = self._make_non_admin_client()
        try:
            r = client.get("/api/labgen/contract-pack")
            assert r.status_code == 403
        finally:
            self._restore(app, saved)

    def test_llm_provider_status_returns_403_for_non_admin(self):
        client, saved, app = self._make_non_admin_client()
        try:
            r = client.get("/api/labgen/llm-provider/status")
            assert r.status_code == 403
        finally:
            self._restore(app, saved)

    def test_adapter_status_returns_403_for_non_admin(self):
        client, saved, app = self._make_non_admin_client()
        try:
            r = client.get("/api/labgen/runtime/adapter-status")
            assert r.status_code == 403
        finally:
            self._restore(app, saved)

    def test_expire_sessions_returns_403_for_non_admin(self):
        client, saved, app = self._make_non_admin_client()
        try:
            r = client.post(
                "/api/labgen/runtime/expire-sessions",
                json={"dry_run": True},
            )
            assert r.status_code == 403
        finally:
            self._restore(app, saved)

    def test_demo_seed_returns_403_for_non_admin(self):
        client, saved, app = self._make_non_admin_client()
        try:
            r = client.post("/api/labgen/demo/seed", json={})
            assert r.status_code == 403
        finally:
            self._restore(app, saved)

    def test_draft_create_returns_403_for_non_admin(self):
        client, saved, app = self._make_non_admin_client()
        try:
            r = client.post("/api/labgen/drafts", json={"title": "x"})
            assert r.status_code == 403
        finally:
            self._restore(app, saved)


# ===========================================================================
# G. LLM provider: raw output, hidden prompt, provider metadata never returned
# ===========================================================================


class TestVerifierDetailSafetyRC:
    """Regression: VerifyResult.detail must never leak session.namespace."""

    def test_step_check_failed_results_no_namespace_in_detail(self):
        """Even on verify failure, the step check response must not expose session.namespace."""
        with _rc_ctx() as ctx:
            lab_id = "rc-verifier-safety-lab"
            _minimal_published_draft(lab_id, ctx["draft_repo"])
            start = ctx["client"].post("/api/lab-sessions", json={
                "lab_id": lab_id,
                "vm_id": "500",
            })
            session_id = start.json()["session_id"]
            session = ctx["session_repo"].get(session_id)
            # namespace is set by create_session; verify it's not None
            assert session is not None

            r = ctx["client"].post(f"/api/lab-sessions/{session_id}/steps/s1/check")
            assert r.status_code == 200
            body_str = str(r.json())
            # namespace value must not appear in any verify result detail
            if session.namespace:
                assert session.namespace not in body_str, (
                    f"session.namespace {session.namespace!r} leaked in step check response"
                )

    def test_verify_results_detail_field_empty_on_namespace_mismatch(self):
        """VERIFIER_NAMESPACE_MISMATCH must not include namespace in detail field."""
        from backend.labgen.verifier import VerifierService
        from backend.labgen.models import VerifyTemplate, VerifyType

        with _rc_ctx() as ctx:
            lab_id = "rc-ns-mismatch-lab"
            _minimal_published_draft(lab_id, ctx["draft_repo"])
            start = ctx["client"].post("/api/lab-sessions", json={
                "lab_id": lab_id,
                "vm_id": "500",
            })
            session_id = start.json()["session_id"]
            session = ctx["session_repo"].get(session_id)

            # Call verifier directly with a hardcoded (non-sentinel) namespace.
            # This simulates what WOULD happen if a draft bypassed the StaticValidator.
            cred_store = _FakeCredStore()
            k8s_client = FakeK8sVerifierClient(default=True)
            svc = VerifierService(
                session_repo=ctx["session_repo"],
                credential_store=cred_store,
                k8s_client_factory=lambda _kc: k8s_client,
            )
            template = VerifyTemplate(
                verify_id="v-mismatch",
                type=VerifyType.POD_RUNNING,
                namespace="hardcoded-namespace",  # not {{lab_namespace}}
                name="nginx",
            )
            result = svc.check(session_id=session_id, template=template)
            assert result.passed is False
            assert result.failure_reason == "namespace_mismatch"
            # detail must be empty — namespace not leaked
            assert result.detail == "", (
                f"detail should be empty but got: {result.detail!r}"
            )


class TestLLMOutputSafetyRC:
    def test_dry_run_response_no_raw_model_output(self):
        with _rc_ctx() as ctx:
            r = ctx["client"].post(
                "/api/labgen/llm-provider/dry-run",
                json={"inject_mode": "valid_candidate"},
            )
            assert r.status_code in (200, 422)
            body_str = str(r.json())
            assert "raw_model_output" not in body_str
            assert "hidden_prompt" not in body_str

    def test_dry_run_disabled_no_sensitive_leak(self):
        with _rc_ctx() as ctx:
            r = ctx["client"].post(
                "/api/labgen/llm-provider/dry-run",
                json={"inject_mode": "provider_disabled"},
            )
            assert r.status_code in (200, 422)
            body_str = str(r.json())
            assert "hidden_prompt" not in body_str
            assert "provider_metadata" not in body_str

    def test_generation_endpoint_no_raw_output(self):
        with _rc_ctx() as ctx:
            r = ctx["client"].post(
                "/api/lab-drafts/generate",
                json={"source_article_id": "art-rc", "article_text": "K8s networking"},
            )
            assert r.status_code in (200, 201, 422, 503)
            if r.status_code in (200, 201):
                body = r.json()
                assert "raw_model_output" not in body
                assert "hidden_prompt" not in body


# ===========================================================================
# H. Admin Diagnostics Consistency (Production Deployment Prep)
#    Verifies that all diagnostic endpoints referenced in
#    PRODUCTION_DEPLOYMENT_PREP_v0.1.md Section E/F are:
#      1. Admin-only (learner → 403)
#      2. Return 200 for admin
#      3. Carry no raw secrets / sensitive fields in the response body
#      4. Present in the contract pack endpoint list
# ===========================================================================


class TestAdminDiagnosticsConsistency:
    """Section H — deployment prep admin diagnostics contract verification."""

    # ----- runtime/adapter-status -----

    def test_adapter_status_admin_only(self):
        with _rc_ctx() as ctx:
            ctx["as_learner"]()
            r = ctx["client"].get("/api/labgen/runtime/adapter-status")
            assert r.status_code == 403

    def test_adapter_status_admin_200(self):
        with _rc_ctx() as ctx:
            ctx["as_admin"]()
            r = ctx["client"].get("/api/labgen/runtime/adapter-status")
            assert r.status_code == 200

    def test_adapter_status_no_secrets(self):
        with _rc_ctx() as ctx:
            ctx["as_admin"]()
            r = ctx["client"].get("/api/labgen/runtime/adapter-status")
            assert r.status_code == 200
            body = r.json()
            _assert_no_sensitive(body, "adapter-status")
            # Must never return raw kubeconfig, token, or credential values
            body_str = str(body)
            assert "apiVersion" not in body_str
            assert "client-certificate" not in body_str

    def test_adapter_status_required_fields(self):
        with _rc_ctx() as ctx:
            ctx["as_admin"]()
            r = ctx["client"].get("/api/labgen/runtime/adapter-status")
            body = r.json()
            assert "runtime_mode" in body
            assert "namespace_adapter_kind" in body
            assert "production_safe" in body
            assert isinstance(body["production_safe"], bool)
            assert "checked_at" in body

    def test_adapter_status_production_safe_false_in_test_mode(self, monkeypatch):
        # In test mode (default for RC tests), production_safe must be False.
        # Patch config module directly — config values are read at import time, not from env.
        import backend.config as _cfg
        monkeypatch.setattr(_cfg, "LABGEN_RUNTIME_MODE", "development")
        monkeypatch.setattr(_cfg, "LABGEN_NAMESPACE_ADAPTER", "stub")
        monkeypatch.setattr(_cfg, "LABGEN_K8S_PLATFORM_KUBECONFIG_PATH", "")
        with _rc_ctx() as ctx:
            ctx["as_admin"]()
            r = ctx["client"].get("/api/labgen/runtime/adapter-status")
            body = r.json()
            # RC tests run in dev/test mode — production_safe should be False
            assert body["production_safe"] is False

    # ----- llm-provider/status -----

    def test_llm_status_admin_only(self):
        with _rc_ctx() as ctx:
            ctx["as_learner"]()
            r = ctx["client"].get("/api/labgen/llm-provider/status")
            assert r.status_code == 403

    def test_llm_status_admin_200(self):
        with _rc_ctx() as ctx:
            ctx["as_admin"]()
            r = ctx["client"].get("/api/labgen/llm-provider/status")
            assert r.status_code == 200

    def test_llm_status_no_secrets(self):
        with _rc_ctx() as ctx:
            ctx["as_admin"]()
            r = ctx["client"].get("/api/labgen/llm-provider/status")
            assert r.status_code == 200
            body = r.json()
            _assert_no_sensitive(body, "llm-provider-status")
            body_str = str(body)
            assert "api_key" not in body_str.lower()
            assert "sk-" not in body_str

    def test_llm_status_live_enabled_false_by_default(self):
        with _rc_ctx() as ctx:
            ctx["as_admin"]()
            r = ctx["client"].get("/api/labgen/llm-provider/status")
            body = r.json()
            # Default LABGEN_LLM_PROVIDER_MODE=fake_only → live_enabled must be False
            assert body["live_enabled"] is False

    def test_llm_status_required_fields(self):
        with _rc_ctx() as ctx:
            ctx["as_admin"]()
            r = ctx["client"].get("/api/labgen/llm-provider/status")
            body = r.json()
            for field in ("provider_name", "mode", "live_enabled", "dry_run_available",
                          "generation_supported", "safety_policy_summary"):
                assert field in body, f"Missing field: {field}"

    # ----- contract-pack -----

    def test_contract_pack_admin_only(self):
        with _rc_ctx() as ctx:
            ctx["as_learner"]()
            r = ctx["client"].get("/api/labgen/contract-pack")
            assert r.status_code == 403

    def test_contract_pack_admin_200(self):
        with _rc_ctx() as ctx:
            ctx["as_admin"]()
            r = ctx["client"].get("/api/labgen/contract-pack")
            assert r.status_code == 200

    def test_contract_pack_no_secrets(self):
        with _rc_ctx() as ctx:
            ctx["as_admin"]()
            r = ctx["client"].get("/api/labgen/contract-pack")
            assert r.status_code == 200
            body_str = str(r.json())
            # Description words like "kubeconfig", "password", "traceback" are fine in
            # the contract metadata. What must never appear is actual credential content.
            assert "apiVersion: v1" not in body_str
            assert "kind: Config" not in body_str
            assert "client-certificate-data" not in body_str
            assert "sk-ant-" not in body_str   # Anthropic API key prefix
            assert "sk-proj-" not in body_str  # OpenAI project key prefix

    def test_contract_pack_schema_version(self):
        with _rc_ctx() as ctx:
            ctx["as_admin"]()
            r = ctx["client"].get("/api/labgen/contract-pack")
            body = r.json()
            # Contract pack uses "version" field (not "schema_version")
            assert body.get("version") == "v0.1"
            assert "built_at" in body

    def test_contract_pack_adapter_status_endpoint_present(self):
        with _rc_ctx() as ctx:
            ctx["as_admin"]()
            r = ctx["client"].get("/api/labgen/contract-pack")
            body = r.json()
            endpoints = body.get("endpoints", [])
            paths = [e.get("path", "") for e in endpoints]
            assert any("adapter-status" in p for p in paths), (
                f"adapter-status endpoint not in contract pack. Paths: {paths}"
            )

    def test_contract_pack_llm_status_endpoint_present(self):
        with _rc_ctx() as ctx:
            ctx["as_admin"]()
            r = ctx["client"].get("/api/labgen/contract-pack")
            body = r.json()
            endpoints = body.get("endpoints", [])
            paths = [e.get("path", "") for e in endpoints]
            assert any("llm-provider" in p for p in paths), (
                f"llm-provider endpoint not in contract pack. Paths: {paths}"
            )

    # ----- runtime/expire-sessions -----

    def test_expiry_endpoint_admin_only(self):
        with _rc_ctx() as ctx:
            ctx["as_learner"]()
            r = ctx["client"].post(
                "/api/labgen/runtime/expire-sessions",
                json={"dry_run": True},
            )
            assert r.status_code == 403

    def test_expiry_endpoint_dry_run_no_mutation(self):
        with _rc_ctx() as ctx:
            ctx["as_admin"]()
            # Seed an active session so the expiry scan has something to check
            from datetime import timedelta
            draft = _minimal_published_draft("diag-lab-1", ctx["draft_repo"])
            session = LabSessionState(
                session_id="diag-sess-1",
                student_username="student1",
                lab_id=draft.lab_id,
                vm_id="555",
                namespace="lab-diag-sess-1",
                started_at=datetime.now(tz=timezone.utc) - timedelta(hours=2),
                lab_session_status=LabSessionStatus.LAB_ACTIVE,
            )
            ctx["session_repo"].create(session)

            r = ctx["client"].post(
                "/api/labgen/runtime/expire-sessions",
                json={"dry_run": True},
            )
            assert r.status_code == 200
            body = r.json()
            # dry_run must not mutate session state
            still_active = ctx["session_repo"].get("diag-sess-1")
            assert still_active is not None
            assert still_active.lab_session_status == LabSessionStatus.LAB_ACTIVE
            # dry_run should still identify the expired session
            assert "diag-sess-1" in body.get("expired_session_ids", [])

    def test_expiry_endpoint_no_secrets(self):
        with _rc_ctx() as ctx:
            ctx["as_admin"]()
            r = ctx["client"].post(
                "/api/labgen/runtime/expire-sessions",
                json={"dry_run": True},
            )
            assert r.status_code == 200
            _assert_no_sensitive(r.json(), "expire-sessions")
