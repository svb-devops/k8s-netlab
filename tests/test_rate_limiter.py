"""Tests for RateLimiter — sliding window enforcement."""
import time

from backend.rate_limiter import RateLimiter


class TestRateLimiter:
    def test_allows_requests_under_limit(self):
        rl = RateLimiter()
        for _ in range(3):
            assert rl.is_allowed("user1", max_requests=5, window_seconds=60) is True

    def test_blocks_when_limit_exceeded(self):
        rl = RateLimiter()
        for _ in range(3):
            rl.is_allowed("user1", max_requests=3, window_seconds=60)
        assert rl.is_allowed("user1", max_requests=3, window_seconds=60) is False

    def test_different_keys_are_independent(self):
        rl = RateLimiter()
        for _ in range(3):
            rl.is_allowed("user1", max_requests=3, window_seconds=60)
        # user2 should still be allowed
        assert rl.is_allowed("user2", max_requests=3, window_seconds=60) is True

    def test_retry_after_returns_positive_when_blocked(self):
        rl = RateLimiter()
        for _ in range(3):
            rl.is_allowed("user1", max_requests=3, window_seconds=60)
        assert rl.retry_after("user1", window_seconds=60) > 0

    def test_retry_after_zero_when_no_requests(self):
        rl = RateLimiter()
        assert rl.retry_after("user1", window_seconds=60) == 0

    def test_window_expiry_allows_again(self):
        rl = RateLimiter()
        for _ in range(3):
            rl.is_allowed("user1", max_requests=3, window_seconds=1)
        # After window expires, should be allowed again
        time.sleep(1.1)
        assert rl.is_allowed("user1", max_requests=3, window_seconds=1) is True


class TestIsOverLimitAndRecord:
    def test_is_over_limit_does_not_record(self):
        """is_over_limit 只检查不记录 — 多次调用不应消耗限额（回归：纯检查应与 record 解耦）。"""
        rl = RateLimiter()
        for _ in range(10):
            assert rl.is_over_limit("key", max_requests=3, window_seconds=60) is False
        # 未调用 record，限额未被消耗，is_allowed 仍应通过
        assert rl.is_allowed("key", max_requests=3, window_seconds=60) is True

    def test_is_over_limit_returns_true_after_record(self):
        """record() 累积足够次数后，is_over_limit 必须返回 True。"""
        rl = RateLimiter()
        for _ in range(3):
            rl.record("key")
        assert rl.is_over_limit("key", max_requests=3, window_seconds=60) is True

    def test_record_increments_independently_of_is_allowed(self):
        """record() 直接追加时间戳，与 is_allowed 的检查路径互相独立。"""
        rl = RateLimiter()
        rl.record("key")
        rl.record("key")
        # 2 次记录后仍未到限额 3，is_over_limit 应返回 False
        assert rl.is_over_limit("key", max_requests=3, window_seconds=60) is False
        rl.record("key")
        # 恰好到限额
        assert rl.is_over_limit("key", max_requests=3, window_seconds=60) is True
