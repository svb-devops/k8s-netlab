"""
Stable machine codes for all runtime failure reasons in LabGen.

Rules:
- Values are stable snake_case strings — never change a value after release.
- Tests assert on .value, not on human-readable text.
- Add new members freely; removing or renaming values is a breaking change.
"""

from enum import Enum


class FailureReason(str, Enum):
    # -- Precheck (lab session start) -----------------------------------------
    PRECHECK_DRAFT_NOT_FOUND = "precheck.draft_not_found"
    PRECHECK_DRAFT_NOT_PUBLISHED = "precheck.draft_not_published"
    PRECHECK_CLEANUP_NOT_DECLARED = "precheck.cleanup_not_declared"
    PRECHECK_VM_NOT_FOUND = "precheck.vm_not_found"
    PRECHECK_VM_NOT_OWNED_BY_STUDENT = "precheck.vm_not_owned_by_student"
    PRECHECK_VM_TAINTED = "precheck.vm_tainted"
    PRECHECK_SESSION_ALREADY_ACTIVE = "precheck.session_already_active"

    # -- Image check ----------------------------------------------------------
    IMAGE_UNRESOLVED = "image_unresolved"
    IMAGE_UNAVAILABLE = "image_unavailable"

    # -- Session start --------------------------------------------------------
    NAMESPACE_CREATE_FAILED = "namespace_create_failed"
    VERIFIER_ROLEBINDING_CREATE_FAILED = "verifier_rolebinding_create_failed"
    VERIFIER_ROLEBINDING_VERIFY_FAILED = "verifier_rolebinding_verify_failed"

    # -- Cleanup --------------------------------------------------------------
    NAMESPACE_CLEANUP_FAILED = "namespace_cleanup_failed"

    # -- Verifier (per-step check) --------------------------------------------
    VERIFIER_SESSION_NOT_FOUND = "session_not_found"
    VERIFIER_SESSION_NOT_ACTIVE = "session_not_active"
    VERIFIER_CLUSTER_SCOPE_NOT_SUPPORTED = "cluster_scope_not_supported"
    VERIFIER_NAMESPACE_MISMATCH = "namespace_mismatch"
    VERIFIER_TYPE_NOT_IMPLEMENTED = "verify_type_not_implemented"
    VERIFIER_CREDENTIAL_MISSING = "credential_missing"

    # -- Session lifecycle ----------------------------------------------------
    LAB_NOT_READY_TO_COMPLETE = "lab_not_ready_to_complete"

    # -- Verifier credential reclaim -----------------------------------------
    VERIFIER_CREDENTIAL_RECLAIM_FAILED = "verifier_credential_reclaim_failed"
    VERIFIER_CREDENTIAL_PATH_UNSAFE = "verifier_credential_path_unsafe"
    VERIFIER_CREDENTIAL_DELETE_FAILED = "verifier_credential_delete_failed"

    # -- Adapter selection (runtime) -----------------------------------------
    ADAPTER_UNSAFE_IN_PRODUCTION = "adapter_unsafe_in_production"
