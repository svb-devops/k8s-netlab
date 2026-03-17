"""
RateLimiter 纯逻辑单元测试 — 专为突变测试设计。

test_rate_limiter.py 已覆盖功能行为；本文件补充针对突变的精确断言：
  - RL-4: retry_after 必须基于 min(ts) 而非 max(ts)
"""

import time

from backend.rate_limiter import RateLimiter


class TestRetryAfterPrecision:
    def test_retry_after_based_on_oldest_request(self):
        """
        RL-4 专项：retry_after 使用 min(ts)（最早的请求）而非 max(ts)（最新的请求）。

        用 mock 时钟精确控制时间戳，避免真实 sleep 和 int() 截断的模糊性：
          - t=0:  第一个请求进入窗口
          - t=5:  第二个请求进入窗口
          - t=5:  查询 retry_after（窗口 10s）
          - min 正确值：int(0 + 10 - 5) = 5
          - max 错误值：int(5 + 10 - 5) = 10
        两者相差 5s，不会因为截断而重叠。
        """
        from unittest.mock import patch

        rl = RateLimiter()
        window = 10

        with patch("backend.rate_limiter.time") as mock_time:
            # t=0: 第一个请求
            mock_time.time.return_value = 0.0
            rl.is_allowed("key", max_requests=2, window_seconds=window)

            # t=5: 第二个请求
            mock_time.time.return_value = 5.0
            rl.is_allowed("key", max_requests=2, window_seconds=window)

            # t=5: 查询 retry_after
            mock_time.time.return_value = 5.0
            ra = rl.retry_after("key", window_seconds=window)

        # min(ts)=0 → int(0+10-5) = 5
        # max(ts)=5 → int(5+10-5) = 10
        assert ra == 5, (
            f"retry_after 应为 5（基于 min 时间戳），实际为 {ra}。"
            f"若结果为 10 说明错误地使用了 max(ts)"
        )

    def test_retry_after_returns_zero_when_empty(self):
        rl = RateLimiter()
        assert rl.retry_after("empty", window_seconds=60) == 0

    def test_retry_after_positive_while_requests_in_window(self):
        """窗口内有请求时 retry_after 应返回正数（最早请求的剩余生命）。"""
        rl = RateLimiter()
        rl.is_allowed("key", max_requests=5, window_seconds=10)
        assert rl.retry_after("key", window_seconds=10) > 0
