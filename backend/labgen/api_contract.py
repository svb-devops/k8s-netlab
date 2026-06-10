"""
Frontend Integration Contract Pack v0.1.

Stable API contract definitions for frontend/UI integration.
No runtime state is mutated by any function here.

Design invariants:
  - build_contract_pack() is deterministic and pure: same output every call.
  - No secrets, tokens, kubeconfig, credentials, or stack traces in any field.
  - No raw LLM output, provider metadata, or hidden prompts.
  - No internal repository paths or private model names.
  - All example response values are sanitized.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Contract category vocabulary
# ---------------------------------------------------------------------------


class ApiContractCategory(str, Enum):
    GENERATION = "generation"
    ADMIN_REVIEW = "admin_review"
    LEARNER_CATALOG = "learner_catalog"
    LEARNER_RUNTIME = "learner_runtime"
    RUNTIME_ACTIONS = "runtime_actions"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ApiContractEndpoint(BaseModel):
    path: str
    method: str                 # GET | POST | PATCH
    summary: str
    category: ApiContractCategory
    auth: str                   # "admin" | "any_authenticated" | "owner_or_admin"
    response_model: str         # Public class name — no internal paths
    is_read_only: bool
    tags: list[str] = Field(default_factory=list)


class ApiContractExample(BaseModel):
    name: str
    category: ApiContractCategory
    description: str
    endpoint_path: str
    response: Any               # Deterministic, sanitized example payload (dict or list)


class SensitiveFieldPolicy(BaseModel):
    # Applies to leaf STRING VALUES only — not JSON field names.
    # e.g. "namespace" prohibits raw K8s namespace strings like "lab-abc-uuid"
    # in response values; it does NOT prohibit field names like cleanup.namespace.
    prohibited_in_response_values: list[str] = Field(default_factory=list)
    prohibited_patterns: list[str] = Field(default_factory=list)
    allowlisted_machine_code_patterns: list[str] = Field(default_factory=list)
    enforcement_note: str


class ApiContractPack(BaseModel):
    version: str
    built_at: str               # ISO 8601 UTC at call time — callers may cache
    endpoints: list[ApiContractEndpoint] = Field(default_factory=list)
    example_responses: list[ApiContractExample] = Field(default_factory=list)
    sensitive_field_policy: SensitiveFieldPolicy
    known_deferred_runtime_checks: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Endpoint catalogue
# ---------------------------------------------------------------------------

_ENDPOINTS: list[ApiContractEndpoint] = [
    # --- generation ---
    ApiContractEndpoint(
        path="/api/lab-drafts/generate",
        method="POST",
        summary="Generate a lab draft from a user prompt using the AI generation pipeline",
        category=ApiContractCategory.GENERATION,
        auth="admin",
        response_model="GenerateLabDraftResponse",
        is_read_only=False,
        tags=["lab-drafts"],
    ),
    # --- admin_review ---
    ApiContractEndpoint(
        path="/api/labgen/drafts/{lab_id}/preview",
        method="GET",
        summary="Read-only learner-safe preview snapshot of a draft",
        category=ApiContractCategory.ADMIN_REVIEW,
        auth="admin",
        response_model="DraftPreviewSnapshot",
        is_read_only=True,
        tags=["labgen"],
    ),
    ApiContractEndpoint(
        path="/api/labgen/drafts/{lab_id}/publish-decision",
        method="GET",
        summary="Evaluate whether a draft is safe to publish (read-only gate check)",
        category=ApiContractCategory.ADMIN_REVIEW,
        auth="admin",
        response_model="PublishDecision",
        is_read_only=True,
        tags=["labgen"],
    ),
    ApiContractEndpoint(
        path="/api/labgen/drafts/{lab_id}/publish",
        method="POST",
        summary="Publish a draft — re-runs validator and image checks before committing",
        category=ApiContractCategory.ADMIN_REVIEW,
        auth="admin",
        response_model="LabDraft",
        is_read_only=False,
        tags=["labgen"],
    ),
    # --- learner_catalog ---
    ApiContractEndpoint(
        path="/api/labs",
        method="GET",
        summary="List all published labs (learner-safe catalog view)",
        category=ApiContractCategory.LEARNER_CATALOG,
        auth="any_authenticated",
        response_model="list[LearnerLabCatalogItem]",
        is_read_only=True,
        tags=["labs"],
    ),
    ApiContractEndpoint(
        path="/api/labs/{lab_id}",
        method="GET",
        summary="Detail view of a published lab including step previews and eligibility",
        category=ApiContractCategory.LEARNER_CATALOG,
        auth="any_authenticated",
        response_model="LearnerLabDetail",
        is_read_only=True,
        tags=["labs"],
    ),
    ApiContractEndpoint(
        path="/api/labs/{lab_id}/start-eligibility",
        method="GET",
        summary="Evaluate whether current user may start a lab (read-only, no side effects)",
        category=ApiContractCategory.LEARNER_CATALOG,
        auth="any_authenticated",
        response_model="LearnerLabEligibility",
        is_read_only=True,
        tags=["labs"],
    ),
    # --- learner_runtime ---
    ApiContractEndpoint(
        path="/api/lab-sessions",
        method="GET",
        summary="List the current user's lab sessions (learner-safe summary list)",
        category=ApiContractCategory.LEARNER_RUNTIME,
        auth="any_authenticated",
        response_model="list[LearnerSessionListItem]",
        is_read_only=True,
        tags=["lab-sessions"],
    ),
    ApiContractEndpoint(
        path="/api/lab-sessions/{session_id}/snapshot",
        method="GET",
        summary="Read-only snapshot of session runtime state (owner or admin)",
        category=ApiContractCategory.LEARNER_RUNTIME,
        auth="owner_or_admin",
        response_model="LearnerSessionSnapshot",
        is_read_only=True,
        tags=["lab-sessions"],
    ),
    # --- runtime_actions ---
    ApiContractEndpoint(
        path="/api/lab-sessions",
        method="POST",
        summary="Start a lab session — creates namespace, binds verifier (learner-owned)",
        category=ApiContractCategory.RUNTIME_ACTIONS,
        auth="any_authenticated",
        response_model="LabSessionState",
        is_read_only=False,
        tags=["lab-sessions"],
    ),
    ApiContractEndpoint(
        path="/api/lab-sessions/{session_id}/steps/{step_id}/check",
        method="POST",
        summary="Run verify checks for the current step and advance if all pass",
        category=ApiContractCategory.RUNTIME_ACTIONS,
        auth="any_authenticated",
        response_model="StepCheckResponse",
        is_read_only=False,
        tags=["lab-sessions"],
    ),
    ApiContractEndpoint(
        path="/api/lab-sessions/{session_id}/complete",
        method="POST",
        summary="Complete a lab session (requires ready_to_complete=true)",
        category=ApiContractCategory.RUNTIME_ACTIONS,
        auth="any_authenticated",
        response_model="LabSessionState",
        is_read_only=False,
        tags=["lab-sessions"],
    ),
    ApiContractEndpoint(
        path="/api/lab-sessions/{session_id}/abort",
        method="POST",
        summary="Abort an active lab session and trigger cleanup",
        category=ApiContractCategory.RUNTIME_ACTIONS,
        auth="any_authenticated",
        response_model="LabSessionState",
        is_read_only=False,
        tags=["lab-sessions"],
    ),
    ApiContractEndpoint(
        path="/api/lab-sessions/{session_id}/audit-events",
        method="GET",
        summary="List runtime audit events for a session (owner or admin)",
        category=ApiContractCategory.RUNTIME_ACTIONS,
        auth="owner_or_admin",
        response_model="list[RuntimeAuditEvent]",
        is_read_only=True,
        tags=["lab-sessions"],
    ),
    # --- provider diagnostics ---
    ApiContractEndpoint(
        path="/api/labgen/llm-provider/status",
        method="GET",
        summary="LLM provider boundary status — mode, dry_run_available, safety policy (admin-only)",
        category=ApiContractCategory.ADMIN_REVIEW,
        auth="admin",
        response_model="LLMProviderStatusResponse",
        is_read_only=True,
        tags=["labgen"],
    ),
    ApiContractEndpoint(
        path="/api/labgen/llm-provider/dry-run",
        method="POST",
        summary="Test provider boundary with dry-run — no draft created, no real LLM (admin-only)",
        category=ApiContractCategory.ADMIN_REVIEW,
        auth="admin",
        response_model="DryRunResponse",
        is_read_only=False,
        tags=["labgen"],
    ),
]


# ---------------------------------------------------------------------------
# Sensitive field policy
# ---------------------------------------------------------------------------

_SENSITIVE_FIELD_POLICY = SensitiveFieldPolicy(
    prohibited_in_response_values=[
        "kubeconfig",
        "token",
        "secret",
        "password",
        "credential",
        "private_key",
        "bearer",
        "jwt",
        "traceback",
        "stack trace",
        "raw exception",
        "namespace",
        "service account",
        "verifier credential",
        "raw command output",
        "raw_model_output",
        "hidden prompt",
        "provider metadata",
        "registry credential",
        "registry token",
        "registry auth",
        "internal registry auth",
        "demo seed registry credential",
        "demo seed runtime internal",
        "api_key",
        "provider_trace_id",
        "chain_of_thought",
    ],
    prohibited_patterns=[
        "eyJ[A-Za-z0-9._-]+\\.[A-Za-z0-9._-]+\\.[A-Za-z0-9._-]+",
        "[A-Za-z0-9+/]{60,}={0,2}",
        "(?i)Bearer\\s+[A-Za-z0-9._=+/\\-]{8,}",
        "Traceback \\(most recent call last\\)",
    ],
    allowlisted_machine_code_patterns=[
        "^[a-z][a-z_]*$",
    ],
    enforcement_note=(
        "sanitize_text() applied to all user-visible string fields before placement "
        "in API response models. FailureReason stable machine codes used instead of "
        "raw exception text. Raw LLM output is never serialized to HTTP responses."
    ),
)


# ---------------------------------------------------------------------------
# Deterministic golden example responses
# ---------------------------------------------------------------------------

_EXAMPLES: list[ApiContractExample] = [
    ApiContractExample(
        name="generate_draft_success_with_template",
        category=ApiContractCategory.GENERATION,
        description="Successful lab draft generation — selected_template_id populated",
        endpoint_path="/api/lab-drafts/generate",
        response={
            "draft_id": "lab-example-001",
            "validation_status": "passed",
            "validation_errors": [],
            "warnings": [],
            "selected_template_id": "k8s_pod_basics",
            "candidate_summary": {
                "title": "Kubernetes Pod Basics",
                "step_count": 2,
                "objective_count": 2,
                "estimated_difficulty": "beginner",
            },
            "review_result": None,
            "repair_result": None,
            "repair_attempted": False,
            "repair_applied": False,
        },
    ),
    ApiContractExample(
        name="generate_draft_with_repair_result",
        category=ApiContractCategory.GENERATION,
        description="Draft generation with repair applied — repair_applied=true",
        endpoint_path="/api/lab-drafts/generate",
        response={
            "draft_id": "lab-example-002",
            "validation_status": "passed",
            "validation_errors": [],
            "warnings": ["Image pinning recommended for production use"],
            "selected_template_id": "k8s_service_basics",
            "candidate_summary": {
                "title": "Kubernetes Service Basics",
                "step_count": 3,
                "objective_count": 3,
                "estimated_difficulty": "beginner",
            },
            "review_result": {
                "issues": [],
                "repair_recommended": False,
                "review_summary": "Draft meets quality standards",
            },
            "repair_result": {
                "repaired_validation_status": "passed",
                "repair_applied": True,
                "repair_warnings": [],
                "rejected_reason": None,
            },
            "repair_attempted": True,
            "repair_applied": True,
        },
    ),
    ApiContractExample(
        name="preview_snapshot",
        category=ApiContractCategory.ADMIN_REVIEW,
        description="Draft preview snapshot — admin review view before publish decision",
        endpoint_path="/api/labgen/drafts/{lab_id}/preview",
        response={
            "draft_id": "lab-example-001",
            "title": "Kubernetes Pod Basics",
            "publish_status": "draft",
            "validation_status": "passed",
            "source_info": {
                "source_type": "generated",
                "selected_template_id": "k8s_pod_basics",
                "generation_warnings": [],
                "repair_applied": False,
            },
            "summary": {
                "objective_count": 2,
                "step_count": 2,
                "check_count": 2,
                "estimated_difficulty": "beginner",
                "template_id": "k8s_pod_basics",
                "has_repair_history": False,
            },
            "objectives": [
                "Deploy a pod and verify it reaches Running state",
                "Inspect pod logs and describe output",
            ],
            "steps": [
                {
                    "step_id": "step-1",
                    "title": "Deploy nginx pod",
                    "learner_goal": "Deploy a basic pod and verify scheduling",
                    "instructions_summary": "Run kubectl to deploy nginx",
                    "expected_outcome_summary": "Pod reaches Running state",
                    "checks": [
                        {
                            "check_id": "v1",
                            "check_type": "pod_running",
                            "description": "Verify pod is running",
                            "safe_expectation_summary": "Pod named nginx is in Running state",
                        }
                    ],
                }
            ],
            "issues": [],
            "image_readiness": {
                "status": "READY",
                "resolved_image_count": 1,
                "unresolved_image_count": 0,
                "blocked_image_count": 0,
                "missing_image_count": 0,
                "issues": [],
                "checked_at": "2026-06-09T00:00:00+00:00",
                "checks_deferred": False,
            },
            "generated_at": "2026-06-09T00:00:00+00:00",
            "updated_at": "2026-06-09T00:00:00+00:00",
            "is_publishable": True,
        },
    ),
    ApiContractExample(
        name="publish_decision_allowed",
        category=ApiContractCategory.ADMIN_REVIEW,
        description="Publish decision gate — ALLOWED, no blocking issues",
        endpoint_path="/api/labgen/drafts/{lab_id}/publish-decision",
        response={
            "status": "ALLOWED",
            "is_publishable": True,
            "draft_id": "lab-example-001",
            "validation_status": "passed",
            "preview_summary": {
                "objective_count": 2,
                "step_count": 2,
                "check_count": 2,
                "estimated_difficulty": "beginner",
                "template_id": "k8s_pod_basics",
                "has_repair_history": False,
            },
            "issues": [],
            "checked_at": "2026-06-09T00:00:00+00:00",
        },
    ),
    ApiContractExample(
        name="publish_decision_blocked",
        category=ApiContractCategory.ADMIN_REVIEW,
        description="Publish decision gate — BLOCKED due to validation failure",
        endpoint_path="/api/labgen/drafts/{lab_id}/publish-decision",
        response={
            "status": "BLOCKED",
            "is_publishable": False,
            "draft_id": "lab-example-003",
            "validation_status": "failed",
            "preview_summary": {
                "objective_count": 1,
                "step_count": 1,
                "check_count": 0,
                "estimated_difficulty": None,
                "template_id": None,
                "has_repair_history": False,
            },
            "issues": [
                {
                    "code": "VALIDATION_FAILED",
                    "message": "Validation failed: draft cannot be published",
                    "severity": "error",
                    "path": None,
                    "source": "validator",
                }
            ],
            "checked_at": "2026-06-09T00:00:00+00:00",
        },
    ),
    ApiContractExample(
        name="publish_decision_blocked_image",
        category=ApiContractCategory.ADMIN_REVIEW,
        description="Publish decision gate — BLOCKED due to unresolved image",
        endpoint_path="/api/labgen/drafts/{lab_id}/publish-decision",
        response={
            "status": "BLOCKED",
            "is_publishable": False,
            "draft_id": "lab-example-004",
            "validation_status": "passed",
            "preview_summary": {
                "objective_count": 1,
                "step_count": 1,
                "check_count": 1,
                "estimated_difficulty": None,
                "template_id": None,
                "has_repair_history": False,
            },
            "issues": [
                {
                    "code": "IMAGE_UNRESOLVED",
                    "message": "Image could not be resolved to an internal registry image",
                    "severity": "error",
                    "path": None,
                    "source": "image_readiness",
                },
                {
                    "code": "IMAGE_READINESS_BLOCKED",
                    "message": "Image readiness check failed — resolve all images before publishing",
                    "severity": "error",
                    "path": None,
                    "source": "image_readiness",
                },
            ],
            "checked_at": "2026-06-09T00:00:00+00:00",
        },
    ),
    ApiContractExample(
        name="learner_catalog_item",
        category=ApiContractCategory.LEARNER_CATALOG,
        description="Single item in learner lab catalog list",
        endpoint_path="/api/labs",
        response={
            "lab_id": "lab-example-001",
            "title": "Kubernetes Pod Basics",
            "summary": "Learn how to deploy and inspect pods in a dedicated K3s namespace",
            "objective_count": 2,
            "step_count": 2,
            "estimated_difficulty": "beginner",
            "template_id": "k8s_pod_basics",
            "published_at": "2026-06-09T00:00:00+00:00",
            "is_startable": True,
        },
    ),
    ApiContractExample(
        name="learner_lab_detail",
        category=ApiContractCategory.LEARNER_CATALOG,
        description="Full learner lab detail including step previews and eligibility",
        endpoint_path="/api/labs/{lab_id}",
        response={
            "lab_id": "lab-example-001",
            "title": "Kubernetes Pod Basics",
            "summary": "Learn how to deploy and inspect pods in a dedicated K3s namespace",
            "objectives": [
                "Deploy a pod and verify it reaches Running state",
                "Inspect pod logs and describe output",
            ],
            "steps_preview": [
                {
                    "step_id": "step-1",
                    "title": "Deploy nginx pod",
                    "learner_goal": "Deploy a basic pod and verify scheduling",
                    "instructions_summary": "Run kubectl to deploy nginx",
                    "expected_outcome_summary": "Pod reaches Running state",
                    "check_count": 1,
                }
            ],
            "estimated_difficulty": "beginner",
            "template_id": "k8s_pod_basics",
            "start_eligibility": {
                "is_startable": True,
                "issues": [],
                "checked_at": "2026-06-09T00:00:00+00:00",
            },
        },
    ),
    ApiContractExample(
        name="start_eligibility_with_runtime_checks_deferred",
        category=ApiContractCategory.LEARNER_CATALOG,
        description=(
            "Start eligibility with RUNTIME_CHECKS_DEFERRED warning — "
            "is_startable=true but image TTL recheck is deferred to lab start"
        ),
        endpoint_path="/api/labs/{lab_id}/start-eligibility",
        response={
            "is_startable": True,
            "issues": [
                {
                    "code": "RUNTIME_CHECKS_DEFERRED",
                    "message": (
                        "Image availability will be verified when the lab starts. "
                        "If an image becomes unavailable between now and start, "
                        "the start attempt will fail."
                    ),
                    "severity": "warning",
                    "source": "runtime",
                }
            ],
            "checked_at": "2026-06-09T00:00:00+00:00",
        },
    ),
    ApiContractExample(
        name="learner_session_snapshot_active",
        category=ApiContractCategory.LEARNER_RUNTIME,
        description="Session snapshot for an active session with one step available",
        endpoint_path="/api/lab-sessions/{session_id}/snapshot",
        response={
            "session_id": "sess-example-001",
            "lab_id": "lab-example-001",
            "title": "Kubernetes Pod Basics",
            "session_state": "LAB_ACTIVE",
            "current_step_id": "step-1",
            "steps": [
                {
                    "step_id": "step-1",
                    "title": "Deploy nginx pod",
                    "learner_goal": "Deploy a basic pod and verify scheduling",
                    "status": "available",
                    "is_current": True,
                    "check_summary": {
                        "last_checked_at": None,
                        "last_result": "not_checked",
                        "safe_message": None,
                        "failure_reason": None,
                    },
                }
            ],
            "runtime_summary": {
                "vm_status": "LAB_ACTIVE",
                "ready_to_complete": False,
                "cleanup_status": None,
                "tainted": None,
                "failure_reason": None,
            },
            "action_availability": {
                "can_check_current_step": True,
                "can_complete": False,
                "can_abort": True,
                "disabled_reasons": [],
            },
            "issues": [],
            "checked_at": "2026-06-09T00:00:00+00:00",
        },
    ),
    ApiContractExample(
        name="learner_session_snapshot_ready_to_complete",
        category=ApiContractCategory.LEARNER_RUNTIME,
        description="Session snapshot after all steps passed — ready_to_complete=true",
        endpoint_path="/api/lab-sessions/{session_id}/snapshot",
        response={
            "session_id": "sess-example-001",
            "lab_id": "lab-example-001",
            "title": "Kubernetes Pod Basics",
            "session_state": "LAB_ACTIVE",
            "current_step_id": None,
            "steps": [
                {
                    "step_id": "step-1",
                    "title": "Deploy nginx pod",
                    "learner_goal": "Deploy a basic pod and verify scheduling",
                    "status": "passed",
                    "is_current": False,
                    "check_summary": None,
                }
            ],
            "runtime_summary": {
                "vm_status": "LAB_ACTIVE",
                "ready_to_complete": True,
                "cleanup_status": None,
                "tainted": None,
                "failure_reason": None,
            },
            "action_availability": {
                "can_check_current_step": False,
                "can_complete": True,
                "can_abort": True,
                "disabled_reasons": [],
            },
            "issues": [],
            "checked_at": "2026-06-09T00:00:00+00:00",
        },
    ),
    ApiContractExample(
        name="audit_events_list",
        category=ApiContractCategory.RUNTIME_ACTIONS,
        description="Audit event list for a completed session",
        endpoint_path="/api/lab-sessions/{session_id}/audit-events",
        response=[
            {
                "schema_version": "1.0",
                "event_id": "evt-example-001",
                "session_id": "sess-example-001",
                "event_type": "lab_start_success",
                "timestamp": "2026-06-09T00:00:00+00:00",
                "failure_reason": None,
                "metadata": {},
            },
            {
                "schema_version": "1.0",
                "event_id": "evt-example-002",
                "session_id": "sess-example-001",
                "event_type": "step_check_passed",
                "timestamp": "2026-06-09T00:01:00+00:00",
                "failure_reason": None,
                "metadata": {"step_id": "step-1"},
            },
            {
                "schema_version": "1.0",
                "event_id": "evt-example-003",
                "session_id": "sess-example-001",
                "event_type": "lab_complete",
                "timestamp": "2026-06-09T00:02:00+00:00",
                "failure_reason": None,
                "metadata": {},
            },
        ],
    ),
    ApiContractExample(
        name="demo_seed_success",
        category=ApiContractCategory.ADMIN_REVIEW,
        description=(
            "[DEMO-ONLY] POST /api/labgen/demo/seed — seeds 8 deterministic demo scenarios. "
            "Admin-only. No real LLM, no real K3s, no real VMs. "
            "Response contains only IDs, scenario names, warnings, and next steps."
        ),
        endpoint_path="/api/labgen/demo/seed",
        response={
            "seeded_scenarios": [
                "PYTHON_BASICS_PUBLISHED",
                "HTTP_API_BASICS_PUBLISHED",
                "DATA_TRANSFORM_IMAGE_BLOCKED_DRAFT",
                "PYTHON_IMAGE_UNRESOLVED_DRAFT",
                "HTTP_IMAGE_NOT_FOUND_DRAFT",
                "RUNTIME_ACTIVE_SESSION",
                "RUNTIME_READY_TO_COMPLETE_SESSION",
                "RUNTIME_CLEANUP_FAILED_TAINTED_SESSION",
            ],
            "created_or_updated_draft_ids": [
                "demo-python-basics-v1",
                "demo-http-api-basics-v1",
                "demo-data-transform-blocked-v1",
                "demo-python-unresolved-v1",
                "demo-http-not-found-v1",
            ],
            "created_or_updated_lab_ids": [
                "demo-python-basics-v1",
                "demo-http-api-basics-v1",
            ],
            "created_or_updated_session_ids": [
                "demo-session-active-v1",
                "demo-session-ready-v1",
                "demo-session-cleanup-failed-v1",
            ],
            "warnings": [],
            "next_steps": [
                {"label": "Admin draft review: demo-python-basics-v1", "path": "/labgen-admin.html?draftId=demo-python-basics-v1"},
                {"label": "Learner catalog (all published labs)", "path": "/labgen-catalog.html"},
                {"label": "Learner lab detail: demo-python-basics-v1", "path": "/labgen-lab.html?labId=demo-python-basics-v1"},
                {"label": "Learner session snapshot: demo-session-active-v1", "path": "/labgen-session.html?sessionId=demo-session-active-v1"},
            ],
            "checked_at": "2026-06-10T00:00:00+00:00",
        },
    ),
    ApiContractExample(
        name="llm_provider_status",
        category=ApiContractCategory.ADMIN_REVIEW,
        description=(
            "GET /api/labgen/llm-provider/status — admin-only provider boundary diagnostics. "
            "live_enabled is always false. No API keys or raw output in response."
        ),
        endpoint_path="/api/labgen/llm-provider/status",
        response={
            "provider_name": "fake",
            "mode": "fake_only",
            "live_enabled": False,
            "dry_run_available": False,
            "timeout_ms": 30000,
            "max_output_tokens": 4096,
            "safety_policy_summary": (
                "Prohibited: raw output, chain of thought, hidden prompts, "
                "provider data, API keys. sanitize_text() applied to all dynamic content."
            ),
            "warnings": [],
        },
    ),
    ApiContractExample(
        name="llm_provider_dry_run_disabled",
        category=ApiContractCategory.ADMIN_REVIEW,
        description=(
            "POST /api/labgen/llm-provider/dry-run — admin-only boundary test. "
            "No draft created. No real LLM. No raw output returned."
        ),
        endpoint_path="/api/labgen/llm-provider/dry-run",
        response={
            "provider_name": "fake",
            "mode": "disabled",
            "candidate_json": None,
            "warnings": [],
            "usage_summary": None,
            "rejected_reason": "provider_disabled",
        },
    ),
]


# ---------------------------------------------------------------------------
# Deferred checks and notes
# ---------------------------------------------------------------------------

_KNOWN_DEFERRED_RUNTIME_CHECKS = [
    "image_ttl_recheck: image availability is checked again at lab start, not just at eligibility evaluation",
    "verifier_credential_availability: VM must have verifier credentials initialized before start",
    "vm_taint_check: if a VM failed cleanup, it is tainted and cannot be reused until manually cleared",
]

_NOTES = [
    "contract version v0.1 reflects the LabGen MVP backend. Breaking field changes will increment the version.",
    "all response models omit internal fields: namespace, vm_id, kubeconfig, credential material, stack traces",
    "LabSessionState (start/complete/abort responses) includes internal fields not safe for direct UI display; "
    "use LearnerSessionSnapshot for learner-facing runtime state",
    "GET /api/labgen/contract-pack itself is admin-only and does not appear in the learner-facing categories",
    "LLM provider boundary (GET /api/labgen/llm-provider/status): live_enabled is always false — "
    "live providers exist as config enum values only and cannot be activated without code change",
]


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------


def build_contract_pack() -> ApiContractPack:
    """Return the current API contract pack.

    Pure function — no I/O, no state mutation, no LLM calls.
    """
    from datetime import datetime, timezone

    return ApiContractPack(
        version="v0.1",
        built_at=datetime.now(tz=timezone.utc).isoformat(),
        endpoints=list(_ENDPOINTS),
        example_responses=list(_EXAMPLES),
        sensitive_field_policy=_SENSITIVE_FIELD_POLICY,
        known_deferred_runtime_checks=list(_KNOWN_DEFERRED_RUNTIME_CHECKS),
        notes=list(_NOTES),
    )
