"""
K8S NetLab - In-memory rate limiter.

Sliding window counter: tracks request timestamps per key and rejects
requests that exceed max_requests within window_seconds.
"""

import time
from collections import defaultdict


class RateLimiter:
    def __init__(self):
        # {key: [timestamp, ...]}
        self._timestamps: dict = defaultdict(list)

    def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> bool:
        """Check limit and record the attempt (for endpoints where all attempts count)."""
        now = time.time()
        cutoff = now - window_seconds
        ts = self._timestamps[key]
        # Evict expired entries
        self._timestamps[key] = [t for t in ts if t > cutoff]
        if len(self._timestamps[key]) >= max_requests:
            return False
        self._timestamps[key].append(now)
        return True

    def is_over_limit(self, key: str, max_requests: int, window_seconds: int) -> bool:
        """Check limit WITHOUT recording — use with record() to count selectively."""
        cutoff = time.time() - window_seconds
        ts = [t for t in self._timestamps[key] if t > cutoff]
        self._timestamps[key] = ts
        return len(ts) >= max_requests

    def record(self, key: str) -> None:
        """Record a single attempt for the given key."""
        self._timestamps[key].append(time.time())

    def retry_after(self, key: str, window_seconds: int) -> int:
        """Seconds until the oldest request expires and a slot opens."""
        ts = self._timestamps.get(key, [])
        if not ts:
            return 0
        return max(0, int(min(ts) + window_seconds - time.time()))


rate_limiter = RateLimiter()
