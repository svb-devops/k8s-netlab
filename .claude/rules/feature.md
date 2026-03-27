# 触发条件：加新功能、实现需求

1. **先写测试**（TDD），让测试先 fail，再实现功能
2. **实现功能**，让测试 pass
3. **确认覆盖率**不低于当前基线（80%）：
   ```bash
   source venv/bin/activate && pytest tests/ -x -q --cov=backend --cov-report=term-missing
   ```
4. **调用 safety-reviewer**（参见 [safety-review-policy.md](safety-review-policy.md)）
   - 判断触发类别，传入 diff + 相关文件 + 测试变更 + 风险点
   - C 类变更（纯注释/文档/格式）→ 跳过
   - 收到 BLOCKER → 必须修复后重审，或触发外部升级
5. **更新 CHANGELOG.md** 的 `[Unreleased]` 段，追加一行 `- feat: <描述>`
6. **commit + push**（pre-push hook 自动跑全量测试）
7. 如功能有通用价值（跨项目可复用的经验/踩坑）→ 写入 `/root/kb/`
