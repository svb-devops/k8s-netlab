# 触发条件：加新功能、实现需求

1. **先写测试**（TDD），让测试先 fail，再实现功能
2. **实现功能**，让测试 pass
3. **确认覆盖率**不低于当前基线（80%）：
   ```bash
   source venv/bin/activate && pytest tests/ -x -q --cov=backend --cov-report=term-missing
   ```
4. **更新 CHANGELOG.md** 的 `[Unreleased]` 段，追加一行 `- feat: <描述>`
5. **commit + push**（pre-push hook 自动跑全量测试）
6. 如功能有通用价值（跨项目可复用的经验/踩坑）→ 写入 `/root/kb/`
