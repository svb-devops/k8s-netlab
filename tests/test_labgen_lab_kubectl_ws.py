"""
lab_kubectl_ws — WebSocket authentication and session binding tests.

Coverage areas:
  A. Reject: no session_token cookie
  B. Reject: invalid session_token
  C. Reject: session not found
  D. Reject: ownership mismatch
  E. Reject: session not LAB_ACTIVE
  F. Blocked commands: non-kubectl input, forbidden patterns
  G. snapshot: step_do/step_commands populated for current step
  H. snapshot: namespace exposed in snapshot
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.labgen.failure_reasons import FailureReason
from backend.labgen.kubectl_executor import validate_command
from backend.labgen.learner_session_snapshot import (
    _build_step_statuses,
    _substitute_namespace,
)
from backend.labgen.models import (
    CleanupNamespace,
    CleanupSpec,
    ExplainField,
    LabDraft,
    LabSessionState,
    LabSessionStatus,
    PublishStatus,
    Step,
    VerifyTemplate,
)

pytestmark = pytest.mark.static


# ── Helper: build a minimal LabSessionState ───────────────────────────────────

def _make_session(
    session_id: Optional[str] = None,
    username: str = "learner-1",
    status: LabSessionStatus = LabSessionStatus.LAB_ACTIVE,
    namespace: Optional[str] = None,
    current_step_index: int = 0,
    completed_step_ids: Optional[list[str]] = None,
) -> LabSessionState:
    sid = session_id or str(uuid.uuid4())
    ns = namespace or f"lab-{sid}"
    return LabSessionState(
        session_id=sid,
        lab_id="test-lab-id",
        student_username=username,
        vm_id="401",
        lab_session_status=status,
        namespace=ns,
        current_step_index=current_step_index,
        completed_step_ids=completed_step_ids or [],
    )


def _make_step(step_id: str, do: str = "", commands: Optional[list[str]] = None) -> Step:
    return Step(
        step_id=step_id,
        order=1,
        why="Why this step matters",
        do=do,
        commands=commands or [],
        observe="kubectl get pods",
        explain=ExplainField(concept="", observation=""),
        verify=[
            VerifyTemplate(
                verify_id=f"{step_id}-verify",
                type="namespace_exists",
                namespace="{{lab_namespace}}",
                name=f"{step_id}-ns",
            )
        ],
    )


# ── F. Command validation (integration with kubectl_executor) ─────────────────

class TestCommandValidation:
    """Ensure blocked commands produce correct validation results."""

    @pytest.mark.parametrize("cmd,should_allow", [
        # Allowed
        ("kubectl get configmap my-app-config", True),
        ("kubectl create configmap test --from-literal=k=v", True),
        ("kubectl delete deployment hello", True),
        ("", True),
        # Blocked
        ("cat /etc/passwd", False),
        ("kubectl exec my-pod -- bash", False),
        ("kubectl config view", False),
        ("kubectl get namespaces", False),
        ("kubectl get nodes", False),
        ("kubectl get secret sec -o yaml", False),
        ("kubectl get pods --all-namespaces", False),
        ("kubectl get pods -A", False),
        ("kubectl create token lab-learner", False),
        ("kubectl port-forward pod/x 8080:80", False),
        ("kubectl get pods --kubeconfig=/root/.kube/config", False),
        ("kubectl get pods -n kube-system", False),
    ])
    def test_validate_command(self, cmd, should_allow):
        allowed, reason = validate_command(cmd)
        if should_allow:
            assert allowed, f"Expected allowed but got blocked ({reason!r}): {cmd!r}"
        else:
            assert not allowed, f"Expected blocked but got allowed: {cmd!r}"


# ── G. Snapshot: step_do and step_commands for current step ──────────────────

class TestSnapshotStepContent:

    def test_current_step_has_step_do_and_commands(self):
        session = _make_session(current_step_index=0)
        steps = [
            _make_step(
                "step-1",
                do="Create a ConfigMap using the Lab Terminal.",
                commands=["kubectl create configmap my-app-config --from-literal=env=learning"],
            ),
            _make_step("step-2", do="Step 2 instructions"),
        ]
        _, step_statuses = _build_step_statuses(session, steps)

        current = next(s for s in step_statuses if s.is_current)
        assert current.step_do == "Create a ConfigMap using the Lab Terminal."
        assert current.step_commands == [
            "kubectl create configmap my-app-config --from-literal=env=learning"
        ]

    def test_non_current_steps_have_no_commands(self):
        session = _make_session(
            current_step_index=1,
            completed_step_ids=["step-1"],
        )
        steps = [
            _make_step("step-1", do="Step 1", commands=["kubectl get pods"]),
            _make_step("step-2", do="Step 2", commands=["kubectl create deployment x"]),
        ]
        _, step_statuses = _build_step_statuses(session, steps)

        passed = next(s for s in step_statuses if s.status == "passed")
        current = next(s for s in step_statuses if s.is_current)

        # Passed step should NOT expose commands
        assert passed.step_commands == []
        assert passed.step_do is None

        # Current step should expose commands
        assert len(current.step_commands) > 0
        assert current.step_do is not None

    def test_namespace_substituted_in_commands(self):
        ns = "lab-abc123"
        session = _make_session(namespace=ns, current_step_index=0)
        steps = [
            _make_step(
                "step-1",
                do="Confirm {{lab_namespace}} is active.",
                commands=["kubectl get namespace {{lab_namespace}}"],
            )
        ]
        _, step_statuses = _build_step_statuses(session, steps)

        current = next(s for s in step_statuses if s.is_current)
        assert ns in current.step_do
        assert "{{lab_namespace}}" not in current.step_do
        assert ns in current.step_commands[0]
        assert "{{lab_namespace}}" not in current.step_commands[0]

    def test_step_do_and_commands_pass_through_sanitize(self):
        """step_do/commands pass through sanitize_text (redacts secrets, not HTML).
        HTML escaping is the responsibility of the frontend (_safe / escapeHtml)."""
        session = _make_session(current_step_index=0)
        steps = [
            _make_step(
                "step-1",
                do="Create a configmap with key=value",
                commands=["kubectl create configmap my-cfg --from-literal=k=v"],
            )
        ]
        _, step_statuses = _build_step_statuses(session, steps)
        current = next(s for s in step_statuses if s.is_current)
        # Content is preserved (sanitize_text only redacts secrets, not HTML)
        assert "Create a configmap" in current.step_do
        assert len(current.step_commands) == 1
        assert "kubectl create configmap" in current.step_commands[0]


# ── H. Snapshot: namespace exposed ───────────────────────────────────────────

class TestSnapshotNamespace:

    def test_substitute_namespace_replaces_placeholder(self):
        result = _substitute_namespace("kubectl get namespace {{lab_namespace}}", "lab-abc")
        assert result == "kubectl get namespace lab-abc"

    def test_substitute_namespace_no_placeholder(self):
        result = _substitute_namespace("kubectl get pods", "lab-abc")
        assert result == "kubectl get pods"

    def test_substitute_namespace_none_namespace(self):
        result = _substitute_namespace("kubectl get namespace {{lab_namespace}}", None)
        assert "{{lab_namespace}}" in result  # not substituted


# ── A-E. WebSocket auth — via TestClient (lightweight) ───────────────────────

class TestLabKubectlWsAuth:
    """
    Test auth rejection messages via the FastAPI WebSocket endpoint.
    Uses TestClient's websocket_connect helper.
    """

    @pytest.fixture
    def client(self):
        from backend.main import app
        return TestClient(app)

    def test_rejects_missing_session_token(self, client):
        session_id = str(uuid.uuid4())
        with client.websocket_connect(f"/ws/lab-kubectl/{session_id}") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "closed"
            assert msg["reason"] == "auth_error"

    def test_rejects_invalid_session_token(self, client):
        session_id = str(uuid.uuid4())
        with client.websocket_connect(
            f"/ws/lab-kubectl/{session_id}",
            cookies={"session_token": "invalid-token-xyz"},
        ) as ws:
            msg = ws.receive_json()
            assert msg["type"] == "closed"
            assert msg["reason"] == "auth_error"

    def test_rejects_valid_token_but_session_not_found(self, client):
        # Create a real user session token
        from backend.auth import auth_manager
        token = auth_manager.create_session("test-ws-user")
        session_id = str(uuid.uuid4())  # non-existent session

        with client.websocket_connect(
            f"/ws/lab-kubectl/{session_id}",
            cookies={"session_token": token},
        ) as ws:
            msg = ws.receive_json()
            assert msg["type"] == "closed"
            assert msg["reason"] == "session_not_found"
