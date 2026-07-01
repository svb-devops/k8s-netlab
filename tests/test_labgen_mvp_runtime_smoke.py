"""
Backend MVP Runtime Smoke Contract Tests.

Validates the complete LabGen runtime contract from draft creation through
session completion and audit queries — using only mocked/fake adapters.
No real K3s, no real Proxmox, no real credential stores.

Coverage:
  - Happy path: create→validate→publish→start→step check→complete→audit
  - Start failure paths: namespace fail, rolebinding fail, image unresolved
  - Step check failure path: verifier returns failed
  - Complete blocked: ready_to_complete=False → 409
  - Abort path: success + cleanup failure (taint)
  - Permission smoke: owner/admin/stranger/unauthorized
  - Response schema stability: field-level assertions on all key responses
  - Sensitive data guard: assert_no_sensitive_runtime_data on failure payloads
"""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.labgen.failure_reasons import FailureReason
from backend.labgen.lab_session_service import (
    LabSessionService,
    StubVMTracker,
    VMTrackerPort,
)
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
    RuntimeAuditEventType,
    Step,
    VerifierCredentialMetadata,
    VerifyTemplate,
    VerifyType,
)
from backend.labgen.namespace_lifecycle import (
    NamespaceLifecyclePort,
    StubNamespaceLifecycleAdapter,
)
from backend.labgen.publish_service import PublishService
from backend.labgen.routes import (
    get_audit_repository,
    get_image_resolver,
    get_publish_service,
    get_repository,
    get_session_repository,
    get_session_service,
    get_step_progression_service,
    require_admin_user,
)
from backend.labgen.runtime_audit import RuntimeAuditRepository, RuntimeAuditService
from backend.labgen.static_validator import StaticValidator
from backend.labgen.step_progression_service import StepProgressionService
from backend.labgen.verifier import FakeK8sVerifierClient, VerifierService

pytestmark = pytest.mark.static


# ===========================================================================
# Sensitive data guard
# ===========================================================================

# Keywords that must never appear in response leaf string values.
# "kubeconfig", "private_key", "traceback", "stack trace", "raw exception",
# "password" are absolute — no allowlist exceptions.
# "token", "secret", "credential" have allowlist rules for known-safe
# lowercase_snake_case machine codes (e.g. "secret_exists", "credential_missing").
_ABSOLUTE_SENSITIVE = frozenset({
    "kubeconfig",
    "private_key",
    "traceback",
    "stack trace",
    "raw exception",
    "password",
})

# Pattern for safe machine codes: only lowercase letters and underscores, ≤ 60 chars.
_MACHINE_CODE_RE = re.compile(r"^[a-z][a-z_]*$")


def _collect_leaf_strings(obj) -> list[str]:
    """Return all leaf string values in a nested dict/list (skips keys)."""
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


def assert_no_sensitive_runtime_data(payload) -> None:
    """Assert that no leaf string value in the response payload contains sensitive data.

    Scans only string VALUES (not JSON keys) to avoid false positives on
    field names like 'credential_type' or 'secret_exists'.

    Allowlist rules:
      - "token": allowed only in lowercase_snake_case machine codes ≤ 60 chars.
        Real JWT / Bearer tokens fail the pattern check (contain ".", "-", capitals).
      - "secret": allowed only in lowercase_snake_case enum values ≤ 40 chars
        (e.g. "secret_exists", "secret_key_exists").
      - "credential": allowed only in lowercase_snake_case machine codes ≤ 60 chars
        (e.g. "credential_missing", "verifier_credential_missing").
    """
    for val in _collect_leaf_strings(payload):
        v = val.lower()

        # Absolute keywords — no exceptions
        for kw in _ABSOLUTE_SENSITIVE:
            assert kw not in v, (
                f"Sensitive keyword {kw!r} found in response value: {val[:120]!r}"
            )

        # "token" — flag unless it looks like a machine code
        if "token" in v:
            is_safe = _MACHINE_CODE_RE.match(val) and len(val) <= 60
            assert is_safe, (
                f"Possible token leak in response value: {val[:120]!r}\n"
                "(real tokens contain dots, hyphens, or mixed case; machine codes do not)"
            )

        # "secret" — flag unless it looks like a known-safe enum value
        if "secret" in v:
            is_safe = _MACHINE_CODE_RE.match(val) and len(val) <= 40
            assert is_safe, (
                f"Possible secret leak in response value: {val[:120]!r}"
            )

        # "credential" — flag unless it looks like a machine code
        if "credential" in v:
            is_safe = _MACHINE_CODE_RE.match(val) and len(val) <= 60
            assert is_safe, (
                f"Possible credential leak in response value: {val[:120]!r}"
            )


# ===========================================================================
# In-memory fakes
# ===========================================================================


class _MemDraftRepo:
    """In-memory LabDraftRepository that simulates JSON roundtrip on write.

    The real flock-based repo serializes via model_dump(mode="json") then
    re-validates on read.  Without this roundtrip, model_copy(update=dict)
    leaves nested fields as raw dicts instead of Pydantic model objects,
    causing AttributeError in StaticValidator and PublishService.
    """

    def __init__(self) -> None:
        self._store: dict[str, LabDraft] = {}

    def _roundtrip(self, draft: LabDraft) -> LabDraft:
        return LabDraft.model_validate(draft.model_dump(mode="json"))

    def create(self, draft: LabDraft) -> LabDraft:
        validated = self._roundtrip(draft)
        self._store[validated.lab_id] = validated
        return validated

    def get(self, lab_id: str) -> Optional[LabDraft]:
        return self._store.get(lab_id)

    def update(self, draft: LabDraft) -> LabDraft:
        validated = self._roundtrip(draft)
        self._store[validated.lab_id] = validated
        return validated


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

    def list_by_student(self, student_username: str) -> list[LabSessionState]:
        return [s for s in self._store.values() if s.student_username == student_username]


class _MemAuditRepo:
    def __init__(self) -> None:
        self._store: dict[str, list[RuntimeAuditEvent]] = {}

    def append(self, event: RuntimeAuditEvent) -> RuntimeAuditEvent:
        self._store.setdefault(event.session_id, []).append(event)
        return event

    def list_by_session(self, session_id: str) -> list[RuntimeAuditEvent]:
        return list(self._store.get(session_id, []))


class _StubImageResolver:
    def __init__(
        self,
        needs_recheck_val: bool = False,
        existence_check_passes: bool = True,
    ) -> None:
        self._needs_recheck = needs_recheck_val
        self._passes = existence_check_passes
        self.recheck_count = 0

    def needs_recheck(self, img: ImageResolutionResult) -> bool:
        return self._needs_recheck

    def check_registry_existence(self, img: ImageResolutionResult) -> ImageResolutionResult:
        self.recheck_count += 1
        return img.model_copy(update={"existence_check_passed": self._passes})


class _FakeCredentialStore:
    """Always reports credentials exist for any vm_id."""

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


class _FailNsCreateAdapter(NamespaceLifecyclePort):
    """namespace create returns False; everything else OK."""

    def create_namespace(self, namespace: str) -> bool:
        return False

    def namespace_exists(self, namespace: str) -> bool:
        return False

    def delete_namespace(self, namespace: str) -> bool:
        return True

    def is_namespace_deleted(self, namespace: str) -> bool:
        return True

    def ensure_verifier_rolebinding(self, namespace: str) -> bool:
        return True

    def verifier_rolebinding_exists(self, namespace: str) -> bool:
        return True


class _FailRolebindingCreateAdapter(NamespaceLifecyclePort):
    """namespace OK; rolebinding create returns False."""

    def create_namespace(self, namespace: str) -> bool:
        return True

    def namespace_exists(self, namespace: str) -> bool:
        return True

    def delete_namespace(self, namespace: str) -> bool:
        return True

    def is_namespace_deleted(self, namespace: str) -> bool:
        return True

    def ensure_verifier_rolebinding(self, namespace: str) -> bool:
        return False

    def verifier_rolebinding_exists(self, namespace: str) -> bool:
        return False


class _FailRolebindingVerifyAdapter(NamespaceLifecyclePort):
    """namespace OK; rolebinding create OK but verify returns False."""

    def create_namespace(self, namespace: str) -> bool:
        return True

    def namespace_exists(self, namespace: str) -> bool:
        return True

    def delete_namespace(self, namespace: str) -> bool:
        return True

    def is_namespace_deleted(self, namespace: str) -> bool:
        return True

    def ensure_verifier_rolebinding(self, namespace: str) -> bool:
        return True

    def verifier_rolebinding_exists(self, namespace: str) -> bool:
        return False


class _FailDeleteAdapter(NamespaceLifecyclePort):
    """namespace create/exists OK; delete returns False → cleanup fails."""

    def create_namespace(self, namespace: str) -> bool:
        return True

    def namespace_exists(self, namespace: str) -> bool:
        return True

    def delete_namespace(self, namespace: str) -> bool:
        return False

    def is_namespace_deleted(self, namespace: str) -> bool:
        return False

    def ensure_verifier_rolebinding(self, namespace: str) -> bool:
        return True

    def verifier_rolebinding_exists(self, namespace: str) -> bool:
        return True


class _MissingCredentialStore:
    """Always reports credentials missing — forces VERIFIER_CREDENTIAL_MISSING."""

    def exists(self, vm_id: str) -> bool:
        return False

    def load(self, vm_id: str):
        raise RuntimeError("no credentials")


class _ContainsEverything:
    """Stand-in for LABGEN_ENABLED_LAB_IDS when the allowlist gate itself isn't
    under test — drafts get fresh UUIDs per test, so membership must trivially
    hold for any of them without pre-enumerating IDs."""

    def __contains__(self, item: object) -> bool:
        return True


# ===========================================================================
# Smoke context manager
# ===========================================================================


@contextmanager
def _smoke_ctx(
    *,
    ns_lifecycle: Optional[NamespaceLifecyclePort] = None,
    vm_tracker: Optional[VMTrackerPort] = None,
    image_resolver=None,
    verifier_client=None,
    credential_store=None,
):
    """Wire all LabGen dependencies with shared in-memory stores.

    Yields a dict with:
      client        — TestClient (single shared instance)
      draft_repo    — _MemDraftRepo
      session_repo  — _MemSessionRepo
      audit_repo    — _MemAuditRepo
      as_user(u)    — switch get_current_user to username u
    """
    from backend.main import app
    from backend.auth_deps import get_current_user

    draft_repo = _MemDraftRepo()
    session_repo = _MemSessionRepo()
    audit_repo = _MemAuditRepo()
    cred_store = credential_store or _FakeCredentialStore()

    audit_svc = RuntimeAuditService(repo=audit_repo)
    img_resolver = image_resolver or _StubImageResolver()

    session_svc = LabSessionService(
        session_repo=session_repo,
        draft_repo=draft_repo,
        vm_tracker=vm_tracker or StubVMTracker(),
        ns_lifecycle=ns_lifecycle or StubNamespaceLifecycleAdapter(),
        image_resolver=img_resolver,
        audit_svc=audit_svc,
    )

    k8s_client = verifier_client or FakeK8sVerifierClient(default=True)
    verifier_svc = VerifierService(
        session_repo=session_repo,
        credential_store=cred_store,
        k8s_client_factory=lambda _kubeconfig: k8s_client,
    )

    step_svc = StepProgressionService(
        session_repo=session_repo,
        draft_repo=draft_repo,
        verifier_svc=verifier_svc,
        audit_svc=audit_svc,
    )

    pub_svc = PublishService(
        validator=StaticValidator(),
        image_resolver=_StubImageResolver(existence_check_passes=True),
    )

    saved = dict(app.dependency_overrides)

    def _set_user(username: str) -> None:
        app.dependency_overrides[get_current_user] = lambda: username

    app.dependency_overrides.update({
        get_repository: lambda: draft_repo,
        get_session_repository: lambda: session_repo,
        get_session_service: lambda: session_svc,
        get_step_progression_service: lambda: step_svc,
        get_audit_repository: lambda: audit_repo,
        get_publish_service: lambda: pub_svc,
        get_image_resolver: lambda: img_resolver,
        require_admin_user: lambda: "admin",
        get_current_user: lambda: "student1",
    })

    client = TestClient(app, raise_server_exceptions=True)

    # This suite tests runtime/schema/permission contracts, not the LABGEN_ENABLED_LAB_IDS
    # allowlist gate itself — every draft here gets a fresh UUID per test, so instead of
    # pre-enumerating IDs, swap in a "contains everything" stand-in. This must NOT touch
    # auth_manager.is_admin — several tests assert ownership-based 403s for "stranger"
    # users, which patching is_admin globally would silently defeat.
    allowlist_patch = patch("backend.labgen.routes.config.LABGEN_ENABLED_LAB_IDS", _ContainsEverything())
    allowlist_patch.start()
    try:
        yield {
            "client": client,
            "draft_repo": draft_repo,
            "session_repo": session_repo,
            "audit_repo": audit_repo,
            "as_user": _set_user,
        }
    finally:
        allowlist_patch.stop()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)


# ---------------------------------------------------------------------------
# Shared request helpers
# ---------------------------------------------------------------------------

_CREATE_DRAFT_BODY = {
    "source_article_id": "art-001",
    "title": "Kubernetes Networking Lab",
    "description": "Learn pod-to-pod networking fundamentals",
    "estimated_duration_minutes": 45,
    "prerequisites": ["docker-basics"],
}

_STEP_WITH_VERIFY = {
    "step_id": "step-1",
    "order": 1,
    "why": "Understand pod scheduling",
    "do": "Deploy nginx and verify it runs",
    "commands": ["kubectl create deployment nginx --image=172.16.100.1:5000/nginx:1.25"],
    "observe": "Pod transitions to Running state",
    "explain": {"concept": "Pod lifecycle", "observation": "Scheduler assigns node"},
    "verify": [{
        "verify_id": "v1",
        "type": "pod_running",
        "namespace": "{{lab_namespace}}",
        "name": "nginx",
    }],
}

_STEP_NO_VERIFY = {
    "step_id": "step-1",
    "order": 1,
    "why": "Understand pod scheduling",
    "do": "Explore the namespace",
    "commands": [],
    "observe": "Namespace exists",
    "explain": {"concept": "Namespaces", "observation": "Isolation unit"},
    "verify": [],
}

_CLEANUP_BODY = {
    "namespace_cleanup": {"type": "delete_namespace", "namespace": "{{lab_namespace}}"}
}


def _create_and_publish_draft(client: TestClient, step: Optional[dict] = None) -> str:
    """Create, patch (if step given), validate, and publish a draft. Returns lab_id."""
    r = client.post("/api/labgen/drafts", json=_CREATE_DRAFT_BODY)
    assert r.status_code == 201, r.text
    lab_id = r.json()["lab_id"]

    if step is not None:
        patch_body: dict = {"steps": [step], "cleanup": _CLEANUP_BODY}
        r = client.patch(f"/api/labgen/drafts/{lab_id}", json=patch_body)
        assert r.status_code == 200, r.text

    r = client.post(f"/api/labgen/drafts/{lab_id}/validate")
    assert r.status_code == 200, r.text

    r = client.post(f"/api/labgen/drafts/{lab_id}/publish")
    assert r.status_code == 200, r.text
    assert r.json()["publish_status"] == "published"
    return lab_id


def _start_session(client: TestClient, lab_id: str, vm_id: str = "501") -> str:
    """POST /api/lab-sessions and return session_id. Caller must set user first."""
    r = client.post("/api/lab-sessions", json={"lab_id": lab_id, "vm_id": vm_id})
    assert r.status_code == 201, r.text
    return r.json()["session_id"]


# ===========================================================================
# TestMVPHappyPath
# ===========================================================================


class TestMVPHappyPath:
    """Full lifecycle: create→validate→publish→start→step check→complete→audit."""

    def test_full_lifecycle_no_verify_templates(self):
        """Step with no verify templates advances automatically; session completes."""
        with _smoke_ctx() as ctx:
            client = ctx["client"]

            lab_id = _create_and_publish_draft(client, step=_STEP_NO_VERIFY)
            ctx["as_user"]("student1")
            session_id = _start_session(client, lab_id)

            # Session is LAB_ACTIVE
            r = client.get(f"/api/lab-sessions/{session_id}")
            assert r.status_code == 200
            assert r.json()["lab_session_status"] == "LAB_ACTIVE"

            # Step check — no verify templates → all_passed=True automatically
            r = client.post(f"/api/lab-sessions/{session_id}/steps/step-1/check")
            assert r.status_code == 200
            data = r.json()
            assert data["all_passed"] is True
            assert data["advanced"] is True
            assert data["ready_to_complete"] is True

            # Complete
            r = client.post(f"/api/lab-sessions/{session_id}/complete")
            assert r.status_code == 200
            assert r.json()["lab_session_status"] == "LAB_CLOSED"

            # Audit events exist
            r = client.get(f"/api/lab-sessions/{session_id}/audit-events")
            assert r.status_code == 200
            event_types = [e["event_type"] for e in r.json()]
            assert "lab_start_success" in event_types
            assert "step_check_passed" in event_types
            assert "lab_complete" in event_types
            assert "cleanup_success" in event_types

    def test_full_lifecycle_with_verifier(self):
        """Step with verify template; FakeK8sVerifierClient returns True → completes."""
        with _smoke_ctx() as ctx:
            client = ctx["client"]
            lab_id = _create_and_publish_draft(client, step=_STEP_WITH_VERIFY)
            ctx["as_user"]("student1")
            session_id = _start_session(client, lab_id)

            r = client.post(f"/api/lab-sessions/{session_id}/steps/step-1/check")
            assert r.status_code == 200
            data = r.json()
            assert data["all_passed"] is True
            assert data["ready_to_complete"] is True

            r = client.post(f"/api/lab-sessions/{session_id}/complete")
            assert r.status_code == 200
            assert r.json()["lab_session_status"] == "LAB_CLOSED"

    def test_image_ttl_recheck_passes(self):
        """Image with needs_recheck=True; existence_check_passes=True → session starts."""
        resolver = _StubImageResolver(needs_recheck_val=True, existence_check_passes=True)
        with _smoke_ctx(image_resolver=resolver) as ctx:
            client = ctx["client"]

            # Inject a resolved image into the draft after publish
            lab_id = _create_and_publish_draft(client, step=_STEP_NO_VERIFY)

            # Manually add a resolved image to the draft repo so _run_image_check fires
            draft = ctx["draft_repo"].get(lab_id)
            img = ImageResolutionResult(
                image_intent="nginx",
                requested_image="172.16.100.1:5000/nginx:1.25",
                resolved_image="172.16.100.1:5000/nginx:1.25",
                image_status=ImageStatus.RESOLVED,
                existence_check_passed=True,
            )
            ctx["draft_repo"].update(draft.model_copy(update={"image_resolution": [img]}))

            ctx["as_user"]("student1")
            session_id = _start_session(client, lab_id)

            assert resolver.recheck_count == 1
            r = client.get(f"/api/lab-sessions/{session_id}")
            assert r.json()["lab_session_status"] == "LAB_ACTIVE"

    def test_audit_events_ordered_and_complete(self):
        """Audit events are ordered chronologically and contain expected types."""
        with _smoke_ctx() as ctx:
            client = ctx["client"]
            lab_id = _create_and_publish_draft(client, step=_STEP_NO_VERIFY)
            ctx["as_user"]("student1")
            session_id = _start_session(client, lab_id)

            client.post(f"/api/lab-sessions/{session_id}/steps/step-1/check")
            client.post(f"/api/lab-sessions/{session_id}/complete")

            r = client.get(f"/api/lab-sessions/{session_id}/audit-events")
            events = r.json()

            types = [e["event_type"] for e in events]
            assert types.index("lab_start_success") < types.index("step_check_passed")
            assert types.index("step_check_passed") < types.index("lab_complete")
            assert types.index("lab_complete") < types.index("cleanup_success")

            for e in events:
                assert "event_id" in e
                assert "session_id" in e
                assert "timestamp" in e

    def test_draft_create_validate_publish_schema(self):
        """Draft API full chain: all response bodies have required schema fields."""
        with _smoke_ctx() as ctx:
            client = ctx["client"]

            r = client.post("/api/labgen/drafts", json=_CREATE_DRAFT_BODY)
            assert r.status_code == 201
            d = r.json()
            assert "lab_id" in d
            assert "title" in d
            assert "publish_status" in d
            assert d["publish_status"] == "draft"

            lab_id = d["lab_id"]

            r = client.post(f"/api/labgen/drafts/{lab_id}/validate")
            assert r.status_code == 200
            d = r.json()
            assert "validator_results" in d
            assert "pollution_level" in d

            r = client.post(f"/api/labgen/drafts/{lab_id}/publish")
            assert r.status_code == 200
            assert r.json()["publish_status"] == "published"


# ===========================================================================
# TestLabStartFailures
# ===========================================================================


class TestLabStartFailures:
    """Lab session start failure paths — each uses a failing adapter."""

    def test_namespace_create_fails(self):
        with _smoke_ctx(ns_lifecycle=_FailNsCreateAdapter()) as ctx:
            client = ctx["client"]
            lab_id = _create_and_publish_draft(client)
            ctx["as_user"]("student1")

            r = client.post("/api/lab-sessions", json={"lab_id": lab_id, "vm_id": "501"})
            assert r.status_code == 201
            data = r.json()
            assert data["lab_session_status"] == "LAB_START_FAILED"
            assert data["failure_reason"] == FailureReason.NAMESPACE_CREATE_FAILED.value

            session_id = data["session_id"]
            audit = ctx["audit_repo"].list_by_session(session_id)
            assert any(e.event_type == RuntimeAuditEventType.LAB_START_FAILED for e in audit)
            assert all(e.event_type != RuntimeAuditEventType.LAB_START_SUCCESS for e in audit)

    def test_rolebinding_create_fails(self):
        with _smoke_ctx(ns_lifecycle=_FailRolebindingCreateAdapter()) as ctx:
            client = ctx["client"]
            lab_id = _create_and_publish_draft(client)
            ctx["as_user"]("student1")

            r = client.post("/api/lab-sessions", json={"lab_id": lab_id, "vm_id": "501"})
            assert r.status_code == 201
            data = r.json()
            assert data["lab_session_status"] == "LAB_START_FAILED"
            assert data["failure_reason"] == FailureReason.VERIFIER_ROLEBINDING_CREATE_FAILED.value

            audit = ctx["audit_repo"].list_by_session(data["session_id"])
            assert any(e.event_type == RuntimeAuditEventType.LAB_START_FAILED for e in audit)

    def test_rolebinding_verify_fails(self):
        with _smoke_ctx(ns_lifecycle=_FailRolebindingVerifyAdapter()) as ctx:
            client = ctx["client"]
            lab_id = _create_and_publish_draft(client)
            ctx["as_user"]("student1")

            r = client.post("/api/lab-sessions", json={"lab_id": lab_id, "vm_id": "501"})
            assert r.status_code == 201
            data = r.json()
            assert data["lab_session_status"] == "LAB_START_FAILED"
            assert data["failure_reason"] == FailureReason.VERIFIER_ROLEBINDING_VERIFY_FAILED.value

    def test_image_unresolved_blocks_start(self):
        with _smoke_ctx() as ctx:
            client = ctx["client"]
            lab_id = _create_and_publish_draft(client)

            # Inject an unresolved image
            draft = ctx["draft_repo"].get(lab_id)
            img = ImageResolutionResult(
                image_intent="nginx",
                requested_image="172.16.100.1:5000/nginx:1.25",
                image_status=ImageStatus.UNRESOLVED,
            )
            ctx["draft_repo"].update(draft.model_copy(update={"image_resolution": [img]}))

            ctx["as_user"]("student1")
            r = client.post("/api/lab-sessions", json={"lab_id": lab_id, "vm_id": "501"})
            assert r.status_code == 201
            data = r.json()
            assert data["lab_session_status"] == "LAB_START_FAILED"
            assert data["failure_reason"] == FailureReason.IMAGE_UNRESOLVED.value

            audit = ctx["audit_repo"].list_by_session(data["session_id"])
            assert any(e.event_type == RuntimeAuditEventType.LAB_START_FAILED for e in audit)

    def test_start_failure_response_no_sensitive_data(self):
        with _smoke_ctx(ns_lifecycle=_FailNsCreateAdapter()) as ctx:
            client = ctx["client"]
            lab_id = _create_and_publish_draft(client)
            ctx["as_user"]("student1")

            r = client.post("/api/lab-sessions", json={"lab_id": lab_id, "vm_id": "501"})
            assert_no_sensitive_runtime_data(r.json())


# ===========================================================================
# TestStepCheckFailure
# ===========================================================================


class TestStepCheckFailure:
    """Step check paths that return failed or error responses."""

    def test_verifier_returns_failed(self):
        """FakeK8sVerifierClient with default=False → all_passed=False, audit event."""
        failing_client = FakeK8sVerifierClient(default=False)
        with _smoke_ctx(verifier_client=failing_client) as ctx:
            client = ctx["client"]
            lab_id = _create_and_publish_draft(client, step=_STEP_WITH_VERIFY)
            ctx["as_user"]("student1")
            session_id = _start_session(client, lab_id)

            r = client.post(f"/api/lab-sessions/{session_id}/steps/step-1/check")
            assert r.status_code == 200
            data = r.json()
            assert data["all_passed"] is False
            assert data["advanced"] is False
            assert data["ready_to_complete"] is False
            assert len(data["verify_results"]) > 0
            assert data["verify_results"][0]["passed"] is False

            # Session status unchanged — still LAB_ACTIVE
            r2 = client.get(f"/api/lab-sessions/{session_id}")
            assert r2.json()["lab_session_status"] == "LAB_ACTIVE"

            audit = ctx["audit_repo"].list_by_session(session_id)
            assert any(e.event_type == RuntimeAuditEventType.STEP_CHECK_FAILED for e in audit)
            assert all(e.event_type != RuntimeAuditEventType.STEP_CHECK_PASSED for e in audit)

    def test_credential_missing_causes_verify_fail(self):
        """VerifierCredentialStore reports missing → step check returns failed."""
        with _smoke_ctx(credential_store=_MissingCredentialStore()) as ctx:
            client = ctx["client"]
            lab_id = _create_and_publish_draft(client, step=_STEP_WITH_VERIFY)
            ctx["as_user"]("student1")
            session_id = _start_session(client, lab_id)

            r = client.post(f"/api/lab-sessions/{session_id}/steps/step-1/check")
            assert r.status_code == 200
            data = r.json()
            assert data["all_passed"] is False
            assert data["verify_results"][0]["failure_reason"] == FailureReason.VERIFIER_CREDENTIAL_MISSING.value

    def test_step_check_wrong_step_id_rejected(self):
        """Requesting a non-current step returns 409."""
        with _smoke_ctx() as ctx:
            client = ctx["client"]
            lab_id = _create_and_publish_draft(client, step=_STEP_NO_VERIFY)
            ctx["as_user"]("student1")
            session_id = _start_session(client, lab_id)

            r = client.post(f"/api/lab-sessions/{session_id}/steps/wrong-step/check")
            assert r.status_code == 409

    def test_step_check_failure_no_sensitive_data(self):
        """Step check failure response must not contain sensitive fields."""
        failing_client = FakeK8sVerifierClient(default=False)
        with _smoke_ctx(verifier_client=failing_client) as ctx:
            client = ctx["client"]
            lab_id = _create_and_publish_draft(client, step=_STEP_WITH_VERIFY)
            ctx["as_user"]("student1")
            session_id = _start_session(client, lab_id)

            r = client.post(f"/api/lab-sessions/{session_id}/steps/step-1/check")
            assert_no_sensitive_runtime_data(r.json())


# ===========================================================================
# TestCompleteBlocked
# ===========================================================================


class TestCompleteBlocked:
    """complete endpoint returns 409 when ready_to_complete is False."""

    def test_complete_blocked_before_step_check(self):
        """ready_to_complete defaults to False — complete must be rejected."""
        with _smoke_ctx() as ctx:
            client = ctx["client"]
            lab_id = _create_and_publish_draft(client, step=_STEP_NO_VERIFY)
            ctx["as_user"]("student1")
            session_id = _start_session(client, lab_id)

            r = client.post(f"/api/lab-sessions/{session_id}/complete")
            assert r.status_code == 409
            assert FailureReason.LAB_NOT_READY_TO_COMPLETE.value in r.text

            # Session state must not have changed to LAB_COMPLETED or LAB_CLOSED
            r2 = client.get(f"/api/lab-sessions/{session_id}")
            assert r2.json()["lab_session_status"] == "LAB_ACTIVE"

    def test_no_audit_event_when_complete_blocked(self):
        """Blocked complete must not produce a LAB_COMPLETE audit event."""
        with _smoke_ctx() as ctx:
            client = ctx["client"]
            lab_id = _create_and_publish_draft(client)
            ctx["as_user"]("student1")
            session_id = _start_session(client, lab_id)

            client.post(f"/api/lab-sessions/{session_id}/complete")

            audit = ctx["audit_repo"].list_by_session(session_id)
            assert all(e.event_type != RuntimeAuditEventType.LAB_COMPLETE for e in audit)


# ===========================================================================
# TestAbortPath
# ===========================================================================


class TestAbortPath:
    """Abort session with and without cleanup failures."""

    def test_abort_success(self):
        """Abort triggers cleanup; ends in LAB_CLOSED with CLEANUP_SUCCESS audit."""
        with _smoke_ctx() as ctx:
            client = ctx["client"]
            lab_id = _create_and_publish_draft(client)
            ctx["as_user"]("student1")
            session_id = _start_session(client, lab_id)

            r = client.post(f"/api/lab-sessions/{session_id}/abort")
            assert r.status_code == 200
            data = r.json()
            assert data["lab_session_status"] == "LAB_CLOSED"
            assert data["cleanup_verified"] is True

            audit = ctx["audit_repo"].list_by_session(session_id)
            types = [e.event_type for e in audit]
            assert RuntimeAuditEventType.LAB_ABORT in types
            assert RuntimeAuditEventType.CLEANUP_SUCCESS in types

    def test_abort_cleanup_failure_taints_vm(self):
        """Delete failure → LAB_CLEANUP_FAILED + CLEANUP_FAILED + VM_TAINTED audit."""
        with _smoke_ctx(ns_lifecycle=_FailDeleteAdapter()) as ctx:
            client = ctx["client"]
            lab_id = _create_and_publish_draft(client)
            ctx["as_user"]("student1")
            session_id = _start_session(client, lab_id)

            r = client.post(f"/api/lab-sessions/{session_id}/abort")
            assert r.status_code == 200
            data = r.json()
            assert data["lab_session_status"] == "LAB_CLEANUP_FAILED"
            assert data["failure_reason"] == FailureReason.NAMESPACE_CLEANUP_FAILED.value
            assert data["cleanup_verified"] is False

            audit = ctx["audit_repo"].list_by_session(session_id)
            types = [e.event_type for e in audit]
            assert RuntimeAuditEventType.CLEANUP_FAILED in types
            assert RuntimeAuditEventType.VM_TAINTED in types

            # VM_TAINTED metadata must only contain vm_id (no credential material)
            taint_events = [e for e in audit if e.event_type == RuntimeAuditEventType.VM_TAINTED]
            assert len(taint_events) == 1
            assert "vm_id" in taint_events[0].metadata
            assert_no_sensitive_runtime_data(taint_events[0].metadata)

    def test_abort_already_terminated_is_409(self):
        """Abort on a terminated session returns 409."""
        with _smoke_ctx() as ctx:
            client = ctx["client"]
            lab_id = _create_and_publish_draft(client)
            ctx["as_user"]("student1")
            session_id = _start_session(client, lab_id)

            client.post(f"/api/lab-sessions/{session_id}/abort")
            r = client.post(f"/api/lab-sessions/{session_id}/abort")
            assert r.status_code == 409


# ===========================================================================
# TestPermissionSmoke
# ===========================================================================


class TestPermissionSmoke:
    """Owner, admin, and stranger access control for session and audit endpoints."""

    def _setup_active_session(self, ctx) -> str:
        client = ctx["client"]
        lab_id = _create_and_publish_draft(client)
        ctx["as_user"]("student1")
        return _start_session(client, lab_id)

    def test_owner_can_complete(self):
        with _smoke_ctx() as ctx:
            client = ctx["client"]
            session_id = self._setup_active_session(ctx)
            # Mark ready_to_complete
            session = ctx["session_repo"].get(session_id)
            session.ready_to_complete = True
            ctx["session_repo"].update(session)

            ctx["as_user"]("student1")
            r = client.post(f"/api/lab-sessions/{session_id}/complete")
            assert r.status_code == 200

    def test_owner_can_abort(self):
        with _smoke_ctx() as ctx:
            client = ctx["client"]
            session_id = self._setup_active_session(ctx)
            ctx["as_user"]("student1")
            r = client.post(f"/api/lab-sessions/{session_id}/abort")
            assert r.status_code == 200

    def test_owner_can_read_audit_events(self):
        with _smoke_ctx() as ctx:
            client = ctx["client"]
            session_id = self._setup_active_session(ctx)
            ctx["as_user"]("student1")
            r = client.get(f"/api/lab-sessions/{session_id}/audit-events")
            assert r.status_code == 200

    def test_stranger_cannot_complete(self):
        with _smoke_ctx() as ctx:
            client = ctx["client"]
            session_id = self._setup_active_session(ctx)
            ctx["as_user"]("stranger")
            r = client.post(f"/api/lab-sessions/{session_id}/complete")
            assert r.status_code == 403

    def test_stranger_cannot_abort(self):
        with _smoke_ctx() as ctx:
            client = ctx["client"]
            session_id = self._setup_active_session(ctx)
            ctx["as_user"]("stranger")
            r = client.post(f"/api/lab-sessions/{session_id}/abort")
            assert r.status_code == 403

    def test_stranger_cannot_read_audit_events(self):
        with _smoke_ctx() as ctx:
            client = ctx["client"]
            session_id = self._setup_active_session(ctx)
            ctx["as_user"]("stranger")
            r = client.get(f"/api/lab-sessions/{session_id}/audit-events")
            assert r.status_code == 403

    def test_admin_can_read_audit_events(self):
        with _smoke_ctx() as ctx:
            client = ctx["client"]
            session_id = self._setup_active_session(ctx)
            ctx["as_user"]("admin")
            with patch("backend.labgen.routes.auth_manager") as mock_am:
                mock_am.is_admin.return_value = True
                r = client.get(f"/api/lab-sessions/{session_id}/audit-events")
                assert r.status_code == 200

    def test_unauthorized_action_produces_no_misleading_audit(self):
        """403 on complete/abort must not create LAB_COMPLETE or LAB_ABORT audit."""
        with _smoke_ctx() as ctx:
            client = ctx["client"]
            session_id = self._setup_active_session(ctx)
            ctx["as_user"]("stranger")

            client.post(f"/api/lab-sessions/{session_id}/complete")
            client.post(f"/api/lab-sessions/{session_id}/abort")

            audit = ctx["audit_repo"].list_by_session(session_id)
            types = [e.event_type for e in audit]
            assert RuntimeAuditEventType.LAB_COMPLETE not in types
            assert RuntimeAuditEventType.LAB_ABORT not in types

    def test_404_on_missing_session(self):
        with _smoke_ctx() as ctx:
            client = ctx["client"]
            ctx["as_user"]("student1")
            fake_id = "00000000-0000-0000-0000-000000000000"
            assert client.get(f"/api/lab-sessions/{fake_id}").status_code == 404
            assert client.post(f"/api/lab-sessions/{fake_id}/complete").status_code == 404
            assert client.post(f"/api/lab-sessions/{fake_id}/abort").status_code == 404
            assert client.get(f"/api/lab-sessions/{fake_id}/audit-events").status_code == 404

    def test_step_check_returns_403_for_stranger(self):
        with _smoke_ctx() as ctx:
            client = ctx["client"]
            session_id = self._setup_active_session(ctx)
            ctx["as_user"]("stranger")
            r = client.post(f"/api/lab-sessions/{session_id}/steps/step-1/check")
            assert r.status_code == 403


# ===========================================================================
# TestResponseSchemaStability
# ===========================================================================


class TestResponseSchemaStability:
    """Field-level assertions on all key API response schemas."""

    def test_draft_response_schema(self):
        with _smoke_ctx() as ctx:
            client = ctx["client"]
            r = client.post("/api/labgen/drafts", json=_CREATE_DRAFT_BODY)
            assert r.status_code == 201
            d = r.json()
            required = ["lab_id", "source_article_id", "title", "description",
                        "publish_status", "steps", "schema_version",
                        "estimated_duration_minutes", "created_at", "updated_at"]
            for f in required:
                assert f in d, f"draft response missing field: {f!r}"

    def test_validate_response_schema(self):
        with _smoke_ctx() as ctx:
            client = ctx["client"]
            r = client.post("/api/labgen/drafts", json=_CREATE_DRAFT_BODY)
            lab_id = r.json()["lab_id"]
            r = client.post(f"/api/labgen/drafts/{lab_id}/validate")
            d = r.json()
            assert "validator_results" in d
            assert "pollution_level" in d
            assert "publish_status" in d
            assert isinstance(d["validator_results"], list)

    def test_publish_response_schema(self):
        with _smoke_ctx() as ctx:
            client = ctx["client"]
            lab_id = _create_and_publish_draft(client)
            r = client.get(f"/api/labgen/drafts/{lab_id}")
            d = r.json()
            assert d["publish_status"] == "published"
            assert "lab_id" in d
            assert "validator_results" in d

    def test_lab_start_response_schema(self):
        with _smoke_ctx() as ctx:
            client = ctx["client"]
            lab_id = _create_and_publish_draft(client)
            ctx["as_user"]("student1")
            r = client.post("/api/lab-sessions", json={"lab_id": lab_id, "vm_id": "501"})
            assert r.status_code == 201
            d = r.json()
            required = ["session_id", "lab_id", "vm_id", "student_username",
                        "lab_session_status", "schema_version",
                        "current_step_index", "ready_to_complete"]
            for f in required:
                assert f in d, f"lab start response missing field: {f!r}"
            assert d["lab_session_status"] == "LAB_ACTIVE"
            assert d["student_username"] == "student1"

    def test_step_check_response_schema(self):
        with _smoke_ctx() as ctx:
            client = ctx["client"]
            lab_id = _create_and_publish_draft(client, step=_STEP_NO_VERIFY)
            ctx["as_user"]("student1")
            session_id = _start_session(client, lab_id)
            r = client.post(f"/api/lab-sessions/{session_id}/steps/step-1/check")
            d = r.json()
            required = ["session_id", "step_id", "all_passed", "advanced",
                        "ready_to_complete", "verify_results", "schema_version"]
            for f in required:
                assert f in d, f"step check response missing field: {f!r}"
            assert d["session_id"] == session_id
            assert d["step_id"] == "step-1"

    def test_complete_response_schema(self):
        with _smoke_ctx() as ctx:
            client = ctx["client"]
            lab_id = _create_and_publish_draft(client, step=_STEP_NO_VERIFY)
            ctx["as_user"]("student1")
            session_id = _start_session(client, lab_id)

            client.post(f"/api/lab-sessions/{session_id}/steps/step-1/check")
            r = client.post(f"/api/lab-sessions/{session_id}/complete")
            d = r.json()
            required = ["session_id", "lab_session_status", "ended_at",
                        "cleanup_verified", "schema_version"]
            for f in required:
                assert f in d, f"complete response missing field: {f!r}"
            assert d["lab_session_status"] == "LAB_CLOSED"
            assert d["ended_at"] is not None

    def test_abort_response_schema(self):
        with _smoke_ctx() as ctx:
            client = ctx["client"]
            lab_id = _create_and_publish_draft(client)
            ctx["as_user"]("student1")
            session_id = _start_session(client, lab_id)
            r = client.post(f"/api/lab-sessions/{session_id}/abort")
            d = r.json()
            required = ["session_id", "lab_session_status", "ended_at",
                        "cleanup_verified", "schema_version"]
            for f in required:
                assert f in d, f"abort response missing field: {f!r}"

    def test_audit_events_response_schema(self):
        with _smoke_ctx() as ctx:
            client = ctx["client"]
            lab_id = _create_and_publish_draft(client)
            ctx["as_user"]("student1")
            session_id = _start_session(client, lab_id)
            r = client.get(f"/api/lab-sessions/{session_id}/audit-events")
            assert r.status_code == 200
            events = r.json()
            assert isinstance(events, list)
            assert len(events) >= 1

            for e in events:
                assert "event_id" in e, f"audit event missing event_id: {e}"
                assert "session_id" in e
                assert "event_type" in e
                assert "timestamp" in e
                assert "schema_version" in e
                # No failure_reason or metadata fields should contain credentials
                assert_no_sensitive_runtime_data(e)


# ===========================================================================
# TestSensitiveDataNoLeak — global coverage
# ===========================================================================


class TestSensitiveDataNoLeak:
    """assert_no_sensitive_runtime_data on all failure response types."""

    def test_audit_events_no_sensitive_data_after_cleanup_failure(self):
        with _smoke_ctx(ns_lifecycle=_FailDeleteAdapter()) as ctx:
            client = ctx["client"]
            lab_id = _create_and_publish_draft(client)
            ctx["as_user"]("student1")
            session_id = _start_session(client, lab_id)
            client.post(f"/api/lab-sessions/{session_id}/abort")

            r = client.get(f"/api/lab-sessions/{session_id}/audit-events")
            assert r.status_code == 200
            assert_no_sensitive_runtime_data(r.json())

    def test_lab_start_failure_no_sensitive_data(self):
        with _smoke_ctx(ns_lifecycle=_FailNsCreateAdapter()) as ctx:
            client = ctx["client"]
            lab_id = _create_and_publish_draft(client)
            ctx["as_user"]("student1")
            r = client.post("/api/lab-sessions", json={"lab_id": lab_id, "vm_id": "501"})
            assert_no_sensitive_runtime_data(r.json())

    def test_complete_response_no_sensitive_data(self):
        with _smoke_ctx() as ctx:
            client = ctx["client"]
            lab_id = _create_and_publish_draft(client, step=_STEP_NO_VERIFY)
            ctx["as_user"]("student1")
            session_id = _start_session(client, lab_id)
            client.post(f"/api/lab-sessions/{session_id}/steps/step-1/check")
            r = client.post(f"/api/lab-sessions/{session_id}/complete")
            assert_no_sensitive_runtime_data(r.json())

    def test_abort_response_no_sensitive_data(self):
        with _smoke_ctx() as ctx:
            client = ctx["client"]
            lab_id = _create_and_publish_draft(client)
            ctx["as_user"]("student1")
            session_id = _start_session(client, lab_id)
            r = client.post(f"/api/lab-sessions/{session_id}/abort")
            assert_no_sensitive_runtime_data(r.json())
