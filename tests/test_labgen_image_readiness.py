"""
ImageReadinessService unit tests.

Coverage areas:
  A. Empty image list → READY
  B. BLOCKED images → status=BLOCKED, IMAGE_BLOCKED issues
  C. UNRESOLVED images → status=UNRESOLVED, IMAGE_UNRESOLVED issues
  D. NOT_FOUND images (resolved but existence_check_passed=False) → NOT_FOUND
  E. READY images (resolved, existence_check_passed=True)
  F. checks_deferred (resolved, existence_check_passed=None) → READY + warning
  G. Mixed batches — worst-case ordering
  H. Counts are accurate
  I. All messages sanitized (no credentials leak)
  J. Exception in evaluate → CHECK_FAILED, safe message
  K. READY + checks_deferred → RUNTIME_IMAGE_RECHECK_DEFERRED warning added
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import patch

import pytest

from backend.labgen.image_readiness import (
    ImageReadinessResult,
    ImageReadinessService,
    ImageReadinessStatus,
)
from backend.labgen.models import ImageResolutionResult, ImageStatus

pytestmark = pytest.mark.static


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolved(
    requested: str = "nginx:alpine",
    intent: str = "nginx",
    resolved: str = "172.16.100.1:5000/nginx:1.25-alpine",
    existence_checked: Optional[bool] = True,
) -> ImageResolutionResult:
    return ImageResolutionResult(
        image_intent=intent,
        requested_image=requested,
        resolved_image=resolved,
        image_status=ImageStatus.RESOLVED,
        existence_check_passed=existence_checked,
    )


def _blocked(
    requested: str = "nginx:latest",
    intent: str = "nginx",
) -> ImageResolutionResult:
    return ImageResolutionResult(
        image_intent=intent,
        requested_image=requested,
        resolved_image=None,
        image_status=ImageStatus.BLOCKED,
        existence_check_passed=None,
    )


def _unresolved(
    requested: str = "unknown:1.0",
    intent: str = "unknown",
) -> ImageResolutionResult:
    return ImageResolutionResult(
        image_intent=intent,
        requested_image=requested,
        resolved_image=None,
        image_status=ImageStatus.UNRESOLVED,
        existence_check_passed=None,
    )


_SENSITIVE_PATTERNS = [
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._=+/\-]{8,}"),
    re.compile(r"(?i)(token|password|secret|private_key|credential|kubeconfig)\s*[=:]\s*\S+"),
    re.compile(r"eyJ[A-Za-z0-9._\-]+\.[A-Za-z0-9._\-]+\.[A-Za-z0-9._\-]+"),
    re.compile(r"[A-Za-z0-9+/]{60,}={0,2}"),
    re.compile(r"Traceback \(most recent call last\)"),
]


def _assert_no_sensitive(result: ImageReadinessResult) -> None:
    for issue in result.issues:
        for pat in _SENSITIVE_PATTERNS:
            assert not pat.search(issue.message), (
                f"Sensitive pattern {pat.pattern!r} in message: {issue.message!r}"
            )


_svc = ImageReadinessService()


# ===========================================================================
# A. Empty list
# ===========================================================================

class TestEmptyList:
    def test_empty_returns_ready(self):
        result = _svc.evaluate([])
        assert result.status == ImageReadinessStatus.READY

    def test_empty_zero_counts(self):
        result = _svc.evaluate([])
        assert result.resolved_image_count == 0
        assert result.unresolved_image_count == 0
        assert result.blocked_image_count == 0
        assert result.missing_image_count == 0

    def test_empty_no_issues(self):
        result = _svc.evaluate([])
        assert result.issues == []

    def test_empty_has_checked_at(self):
        result = _svc.evaluate([])
        datetime.fromisoformat(result.checked_at)  # valid ISO 8601


# ===========================================================================
# B. BLOCKED images
# ===========================================================================

class TestBlockedImages:
    def test_single_blocked_status(self):
        result = _svc.evaluate([_blocked()])
        assert result.status == ImageReadinessStatus.BLOCKED

    def test_single_blocked_count(self):
        result = _svc.evaluate([_blocked()])
        assert result.blocked_image_count == 1

    def test_single_blocked_issue_code(self):
        result = _svc.evaluate([_blocked()])
        codes = [i.code for i in result.issues]
        assert "IMAGE_BLOCKED" in codes

    def test_single_blocked_issue_severity(self):
        result = _svc.evaluate([_blocked()])
        errors = [i for i in result.issues if i.code == "IMAGE_BLOCKED"]
        assert all(i.severity == "error" for i in errors)

    def test_blocked_source_is_image_resolver(self):
        result = _svc.evaluate([_blocked()])
        issue = next(i for i in result.issues if i.code == "IMAGE_BLOCKED")
        assert issue.source == "image_resolver"

    def test_multiple_blocked_correct_count(self):
        result = _svc.evaluate([_blocked("a:latest"), _blocked("b:latest")])
        assert result.blocked_image_count == 2
        blocked_issues = [i for i in result.issues if i.code == "IMAGE_BLOCKED"]
        assert len(blocked_issues) == 2

    def test_blocked_messages_sanitized(self):
        result = _svc.evaluate([_blocked()])
        _assert_no_sensitive(result)


# ===========================================================================
# C. UNRESOLVED images
# ===========================================================================

class TestUnresolvedImages:
    def test_single_unresolved_status(self):
        result = _svc.evaluate([_unresolved()])
        assert result.status == ImageReadinessStatus.UNRESOLVED

    def test_single_unresolved_count(self):
        result = _svc.evaluate([_unresolved()])
        assert result.unresolved_image_count == 1

    def test_single_unresolved_issue_code(self):
        result = _svc.evaluate([_unresolved()])
        codes = [i.code for i in result.issues]
        assert "IMAGE_UNRESOLVED" in codes

    def test_unresolved_severity_error(self):
        result = _svc.evaluate([_unresolved()])
        issue = next(i for i in result.issues if i.code == "IMAGE_UNRESOLVED")
        assert issue.severity == "error"
        assert issue.source == "image_resolver"

    def test_unresolved_messages_sanitized(self):
        result = _svc.evaluate([_unresolved()])
        _assert_no_sensitive(result)


# ===========================================================================
# D. NOT_FOUND (resolved + existence_check_passed=False)
# ===========================================================================

class TestNotFoundImages:
    def test_not_found_status(self):
        result = _svc.evaluate([_resolved(existence_checked=False)])
        assert result.status == ImageReadinessStatus.NOT_FOUND

    def test_not_found_count(self):
        result = _svc.evaluate([_resolved(existence_checked=False)])
        assert result.missing_image_count == 1

    def test_not_found_resolved_count_incremented(self):
        result = _svc.evaluate([_resolved(existence_checked=False)])
        assert result.resolved_image_count == 1

    def test_not_found_issue_code(self):
        result = _svc.evaluate([_resolved(existence_checked=False)])
        codes = [i.code for i in result.issues]
        assert "IMAGE_NOT_FOUND" in codes

    def test_not_found_issue_severity(self):
        result = _svc.evaluate([_resolved(existence_checked=False)])
        issue = next(i for i in result.issues if i.code == "IMAGE_NOT_FOUND")
        assert issue.severity == "error"
        assert issue.source == "registry_check"

    def test_not_found_messages_sanitized(self):
        result = _svc.evaluate([_resolved(existence_checked=False)])
        _assert_no_sensitive(result)


# ===========================================================================
# E. READY (resolved, existence_check_passed=True)
# ===========================================================================

class TestReadyImages:
    def test_single_ready_status(self):
        result = _svc.evaluate([_resolved(existence_checked=True)])
        assert result.status == ImageReadinessStatus.READY

    def test_single_ready_no_blocking_issues(self):
        result = _svc.evaluate([_resolved(existence_checked=True)])
        blocking = [i for i in result.issues if i.severity == "error"]
        assert blocking == []

    def test_single_ready_count(self):
        result = _svc.evaluate([_resolved(existence_checked=True)])
        assert result.resolved_image_count == 1

    def test_multiple_ready_all_clear(self):
        result = _svc.evaluate([
            _resolved("nginx:alpine", existence_checked=True),
            _resolved("busybox:1.36", existence_checked=True),
        ])
        assert result.status == ImageReadinessStatus.READY
        assert result.resolved_image_count == 2
        blocking = [i for i in result.issues if i.severity == "error"]
        assert blocking == []


# ===========================================================================
# F. checks_deferred (resolved, existence_check_passed=None)
# ===========================================================================

class TestChecksDeferred:
    def test_deferred_still_ready(self):
        result = _svc.evaluate([_resolved(existence_checked=None)])
        assert result.status == ImageReadinessStatus.READY

    def test_deferred_flag_set(self):
        result = _svc.evaluate([_resolved(existence_checked=None)])
        assert result.checks_deferred is True

    def test_deferred_warning_issue_added(self):
        result = _svc.evaluate([_resolved(existence_checked=None)])
        codes = [i.code for i in result.issues]
        assert "RUNTIME_IMAGE_RECHECK_DEFERRED" in codes

    def test_deferred_warning_severity(self):
        result = _svc.evaluate([_resolved(existence_checked=None)])
        issue = next(i for i in result.issues if i.code == "RUNTIME_IMAGE_RECHECK_DEFERRED")
        assert issue.severity == "warning"
        assert issue.source == "registry_check"

    def test_not_deferred_when_existence_checked(self):
        result = _svc.evaluate([_resolved(existence_checked=True)])
        assert result.checks_deferred is False
        codes = [i.code for i in result.issues]
        assert "RUNTIME_IMAGE_RECHECK_DEFERRED" not in codes

    def test_not_deferred_when_blocked(self):
        # Blocking issues suppress deferred warning
        result = _svc.evaluate([_blocked()])
        assert result.checks_deferred is False
        codes = [i.code for i in result.issues]
        assert "RUNTIME_IMAGE_RECHECK_DEFERRED" not in codes


# ===========================================================================
# G. Mixed batches — worst-case ordering (BLOCKED > UNRESOLVED > NOT_FOUND > READY)
# ===========================================================================

class TestMixedBatches:
    def test_blocked_wins_over_unresolved(self):
        result = _svc.evaluate([_blocked(), _unresolved()])
        assert result.status == ImageReadinessStatus.BLOCKED

    def test_blocked_wins_over_not_found(self):
        result = _svc.evaluate([_blocked(), _resolved(existence_checked=False)])
        assert result.status == ImageReadinessStatus.BLOCKED

    def test_blocked_wins_over_ready(self):
        result = _svc.evaluate([_blocked(), _resolved(existence_checked=True)])
        assert result.status == ImageReadinessStatus.BLOCKED

    def test_unresolved_wins_over_not_found(self):
        result = _svc.evaluate([_unresolved(), _resolved(existence_checked=False)])
        assert result.status == ImageReadinessStatus.UNRESOLVED

    def test_unresolved_wins_over_ready(self):
        result = _svc.evaluate([_unresolved(), _resolved(existence_checked=True)])
        assert result.status == ImageReadinessStatus.UNRESOLVED

    def test_not_found_wins_over_ready(self):
        result = _svc.evaluate([_resolved(existence_checked=False), _resolved(existence_checked=True)])
        assert result.status == ImageReadinessStatus.NOT_FOUND

    def test_mixed_counts_accurate(self):
        result = _svc.evaluate([
            _blocked(),
            _unresolved(),
            _resolved(existence_checked=False),
            _resolved(existence_checked=True),
        ])
        assert result.blocked_image_count == 1
        assert result.unresolved_image_count == 1
        assert result.missing_image_count == 1
        assert result.resolved_image_count == 2  # both NOT_FOUND + READY increment resolved_count

    def test_mixed_all_issue_codes_present(self):
        result = _svc.evaluate([
            _blocked(),
            _unresolved(),
            _resolved(existence_checked=False),
        ])
        codes = {i.code for i in result.issues}
        assert "IMAGE_BLOCKED" in codes
        assert "IMAGE_UNRESOLVED" in codes
        assert "IMAGE_NOT_FOUND" in codes


# ===========================================================================
# H. Counts accuracy
# ===========================================================================

class TestCountAccuracy:
    def test_resolved_count_includes_all_resolved_status(self):
        imgs = [
            _resolved(existence_checked=True),
            _resolved(existence_checked=False),
            _resolved(existence_checked=None),
        ]
        result = _svc.evaluate(imgs)
        assert result.resolved_image_count == 3

    def test_zero_counts_when_all_ready(self):
        result = _svc.evaluate([_resolved(existence_checked=True)])
        assert result.blocked_image_count == 0
        assert result.unresolved_image_count == 0
        assert result.missing_image_count == 0


# ===========================================================================
# I. Safety — messages sanitized
# ===========================================================================

class TestSafetyMessages:
    def test_blocked_message_no_raw_url(self):
        """Message must not include raw registry URL."""
        result = _svc.evaluate([_blocked()])
        for issue in result.issues:
            assert "172.16.100.1:5000" not in issue.message or issue.severity != "error"

    def test_unresolved_message_safe(self):
        result = _svc.evaluate([_unresolved(requested="docker.io/nginx:1.25")])
        # 'docker.io/nginx:1.25' is the requested image — it may appear in path, not message
        # but message must not contain credential patterns
        _assert_no_sensitive(result)

    def test_not_found_message_safe(self):
        result = _svc.evaluate([_resolved(existence_checked=False)])
        _assert_no_sensitive(result)

    def test_deferred_message_safe(self):
        result = _svc.evaluate([_resolved(existence_checked=None)])
        _assert_no_sensitive(result)


# ===========================================================================
# J. Exception in evaluate → CHECK_FAILED
# ===========================================================================

class TestCheckFailed:
    def test_exception_returns_check_failed(self):
        svc = ImageReadinessService()
        # Inject a bad input that triggers an internal exception
        with patch.object(svc, "_evaluate_images", side_effect=RuntimeError("boom")):
            result = svc.evaluate([_resolved()])
        assert result.status == ImageReadinessStatus.CHECK_FAILED

    def test_exception_has_safe_message(self):
        svc = ImageReadinessService()
        with patch.object(svc, "_evaluate_images", side_effect=RuntimeError("boom")):
            result = svc.evaluate([_resolved()])
        assert result.issues
        issue = result.issues[0]
        assert issue.code == "IMAGE_CHECK_FAILED"
        assert issue.severity == "error"
        # Must not expose raw exception text
        assert "boom" not in issue.message

    def test_exception_no_traceback_in_message(self):
        svc = ImageReadinessService()
        with patch.object(svc, "_evaluate_images", side_effect=RuntimeError("traceback")):
            result = svc.evaluate([_resolved()])
        for issue in result.issues:
            assert "Traceback" not in issue.message
