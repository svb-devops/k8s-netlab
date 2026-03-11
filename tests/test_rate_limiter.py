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
