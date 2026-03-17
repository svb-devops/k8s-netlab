#!/usr/bin/env python3
"""
手工突变测试 — 验证测试套件本身能真正捕获 bug。

对以下纯逻辑模块注入突变，期望至少一个测试因此失败：
  - backend/rate_limiter.py  （滑动窗口逻辑）
  - backend/password_utils.py（bcrypt / SHA-256 判断逻辑）

运行方式：
  source venv/bin/activate
  python scripts/mutation_test.py

突变得分 = killed / total，目标 ≥ 80%。
"""

import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTEST_CMD = [
    sys.executable, "-m", "pytest",
    "tests/test_rate_limiter.py",
    "tests/test_rate_limiter_unit.py",
    "tests/test_auth.py",
    "tests/test_password_utils.py",
    "--no-cov", "-q", "--tb=no",
]

MUTATIONS = [
    # ── rate_limiter.py ──────────────────────────────────────────────
    {
        "id": "RL-1",
        "desc": "is_allowed: >= 改 > （边界 off-by-one，max 时应拒绝但变为接受）",
        "file": "backend/rate_limiter.py",
        "old": "if len(self._timestamps[key]) >= max_requests:",
        "new": "if len(self._timestamps[key]) > max_requests:",
    },
    {
        "id": "RL-2",
        "desc": "is_allowed: 条件取反 → 始终接受",
        "file": "backend/rate_limiter.py",
        "old": "if len(self._timestamps[key]) >= max_requests:\n            return False\n        self._timestamps[key].append(now)\n        return True",
        "new": "if len(self._timestamps[key]) >= max_requests:\n            return True\n        self._timestamps[key].append(now)\n        return False",
    },
    {
        "id": "RL-3",
        "desc": "is_allowed: 不清除过期记录 → 窗口永不滑动",
        "file": "backend/rate_limiter.py",
        "old": "self._timestamps[key] = [t for t in ts if t > cutoff]",
        "new": "pass  # mutation: skip eviction",
    },
    {
        "id": "RL-4",
        "desc": "retry_after: min 改 max → 返回最晚过期时间（值偏大）",
        "file": "backend/rate_limiter.py",
        "old": "return max(0, int(min(ts) + window_seconds - time.time()))",
        "new": "return max(0, int(max(ts) + window_seconds - time.time()))",
    },
    # ── password_utils.py ────────────────────────────────────────────
    {
        "id": "PW-1",
        "desc": "needs_upgrade: 返回值取反 → bcrypt 被识别为需要升级",
        "file": "backend/password_utils.py",
        "old": "return not stored_hash.startswith((\"$2b$\", \"$2a$\", \"$2y$\"))",
        "new": "return stored_hash.startswith((\"$2b$\", \"$2a$\", \"$2y$\"))",
    },
    {
        "id": "PW-2",
        "desc": "verify_password: bcrypt 分支始终返回 False → 所有用户无法登录",
        "file": "backend/password_utils.py",
        "old": "return bcrypt.checkpw(\n                password.encode(\"utf-8\"),\n                stored_hash.encode(\"utf-8\"),\n            )",
        "new": "return False  # mutation",
    },
    {
        "id": "PW-3",
        "desc": "verify_password: SHA-256 比较取反 → 错误密码反而通过",
        "file": "backend/password_utils.py",
        "old": "return sha256 == stored_hash",
        "new": "return sha256 != stored_hash",
    },
    {
        "id": "PW-4",
        "desc": "verify_password: 异常时返回 True → 无效 hash 被错误放行",
        "file": "backend/password_utils.py",
        "old": "        logger.error(f\"Password verification error: {e}\")\n        return False",
        "new": "        logger.error(f\"Password verification error: {e}\")\n        return True  # mutation",
    },
]


def run_pytest() -> bool:
    """返回 True 表示测试有失败（突变被杀死）。"""
    result = subprocess.run(PYTEST_CMD, cwd=ROOT, capture_output=True, text=True)
    return result.returncode != 0


def apply_mutation(file: str, old: str, new: str):
    path = ROOT / file
    content = path.read_text()
    if old not in content:
        raise ValueError(f"在 {file} 中找不到目标字符串：\n{old}")
    path.write_text(content.replace(old, new, 1))


def revert_mutation(file: str, old: str, new: str):
    path = ROOT / file
    content = path.read_text()
    path.write_text(content.replace(new, old, 1))


def main():
    print("=" * 60)
    print("手工突变测试")
    print("=" * 60)

    # 基准：确认原始测试全绿
    print("\n[基准] 运行原始测试套件...")
    if run_pytest():
        print("ERROR: 原始测试套件存在失败，请先修复后再运行突变测试。")
        sys.exit(1)
    print("[基准] 通过 ✓\n")

    killed = 0
    survived = []

    for m in MUTATIONS:
        print(f"[{m['id']}] {m['desc']}")
        try:
            apply_mutation(m["file"], m["old"], m["new"])
            died = run_pytest()
            if died:
                print(f"  → KILLED ✓")
                killed += 1
            else:
                print(f"  → SURVIVED ✗  ← 测试未能捕获此 bug！")
                survived.append(m)
        except ValueError as e:
            print(f"  → SKIP（{e}）")
        finally:
            try:
                revert_mutation(m["file"], m["old"], m["new"])
            except Exception:
                pass

    total = len(MUTATIONS)
    score = killed / total * 100
    print("\n" + "=" * 60)
    print(f"突变得分：{killed}/{total} = {score:.0f}%  （目标 ≥ 80%）")

    if survived:
        print("\n存活的突变（需要补充测试）：")
        for m in survived:
            print(f"  [{m['id']}] {m['desc']}")

    if score < 80:
        print("\nFAIL: 突变得分低于 80%")
        sys.exit(1)
    else:
        print("\nPASS ✓")
        sys.exit(0)


if __name__ == "__main__":
    main()
