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
    PRECHECK_LINUX_LEARNER_NOT_SUPPORTED = "precheck.linux_learner_not_yet_available"
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

    # -- Runtime precheck (Contract §11 conditions 4 and 6) ------------------
    RUNTIME_PRECHECK_FAILED = "runtime_precheck.failed"
    RUNTIME_PRECHECK_CONDITION_4_FAILED = "runtime_precheck.condition_4_failed"
    RUNTIME_PRECHECK_CONDITION_6_FAILED = "runtime_precheck.condition_6_failed"

    # -- Session timeout (Contract §12 LAB_TIMEOUT) ---------------------------
    LAB_TIMEOUT = "lab_timeout"

    # -- Namespace lifecycle (K8s adapter) ------------------------------------
    NAMESPACE_STUCK_TERMINATING = "namespace_stuck_terminating"
    K8S_API_UNAVAILABLE = "k8s_api_unavailable"
    NAMESPACE_CONFIG_MISSING = "namespace_config_missing"
    NAMESPACE_INVALID_NAME = "namespace_invalid_name"
    NAMESPACE_ADAPTER_CONFIG_UNSAFE = "namespace_adapter_config_unsafe"

    # -- Internal rehearsal bridge --------------------------------------------
    REHEARSAL_DRAFT_NOT_FOUND = "rehearsal.draft_not_found"
    REHEARSAL_DRAFT_NOT_ARTICLE_GENERATED = "rehearsal.draft_not_article_generated"
    REHEARSAL_CLEANUP_NOT_DECLARED = "rehearsal.cleanup_not_declared"
    REHEARSAL_VM_NOT_FOUND = "rehearsal.vm_not_found"
    REHEARSAL_VM_NOT_OWNED = "rehearsal.vm_not_owned"
    REHEARSAL_VM_TAINTED = "rehearsal.vm_tainted"
    REHEARSAL_SESSION_ALREADY_ACTIVE = "rehearsal.session_already_active"

    # -- Linux verifier (workspace-scoped, filesystem-only) -------------------
    LINUX_WORKSPACE_NOT_FOUND = "linux.workspace_not_found"
    LINUX_WORKSPACE_NOT_ACTIVE = "linux.workspace_not_active"
    LINUX_PATH_ESCAPE = "linux.path_escape"
    LINUX_FILE_NOT_FOUND = "linux.file_not_found"
    LINUX_DIRECTORY_NOT_FOUND = "linux.directory_not_found"
    LINUX_CONTENT_MISMATCH = "linux.content_mismatch"
    LINUX_FILE_TOO_LARGE = "linux.file_too_large"
    LINUX_MODE_MISMATCH = "linux.mode_mismatch"
    LINUX_RESIDUAL_FILES_FOUND = "linux.residual_files_found"
    LINUX_VERIFY_TYPE_NOT_SUPPORTED = "linux.verify_type_not_supported"
    LINUX_VERIFIER_NOT_CONFIGURED = "linux.verifier_not_configured"

    # -- Linux internal rehearsal bridge -------------------------------------
    LINUX_REHEARSAL_DRAFT_NOT_FOUND = "linux_rehearsal.draft_not_found"
    LINUX_REHEARSAL_NOT_LINUX_DOMAIN = "linux_rehearsal.not_linux_domain"
    LINUX_REHEARSAL_MISSING_SANDBOX_POLICY = "linux_rehearsal.missing_sandbox_policy"
    LINUX_REHEARSAL_UNSAFE_SANDBOX_POLICY = "linux_rehearsal.unsafe_sandbox_policy"
    LINUX_REHEARSAL_MISSING_CLEANUP = "linux_rehearsal.missing_cleanup"
    LINUX_REHEARSAL_MISSING_VERIFIERS = "linux_rehearsal.missing_verifiers"
    LINUX_REHEARSAL_PLACEHOLDER_IN_COMMANDS = "linux_rehearsal.placeholder_in_commands"
    LINUX_REHEARSAL_SESSION_ALREADY_ACTIVE = "linux_rehearsal.session_already_active"
    LINUX_REHEARSAL_WORKSPACE_CREATE_FAILED = "linux_rehearsal.workspace_create_failed"
    LINUX_REHEARSAL_CLEANUP_FAILED = "linux_rehearsal.cleanup_failed"
    LINUX_REHEARSAL_RESIDUAL_FILES_FOUND = "linux_rehearsal.residual_files_found"
    LINUX_REHEARSAL_NOT_READY_TO_COMPLETE = "linux_rehearsal.not_ready_to_complete"
    LINUX_REHEARSAL_SESSION_NOT_FOUND = "linux_rehearsal.session_not_found"
    LINUX_REHEARSAL_SESSION_NOT_ACTIVE = "linux_rehearsal.session_not_active"
    LINUX_REHEARSAL_STEP_NOT_FOUND = "linux_rehearsal.step_not_found"
    LINUX_REHEARSAL_STEP_NOT_CURRENT = "linux_rehearsal.step_not_current"
    LINUX_REHEARSAL_COMMAND_POLICY_REJECTED = "linux_rehearsal.command_policy_rejected"
    LINUX_REHEARSAL_COMMAND_PARSE_ERROR = "linux_rehearsal.command_parse_error"
