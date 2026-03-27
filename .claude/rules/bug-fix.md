# 触发条件：修 bug、定位问题、复现错误

每次必须完整执行，不得跳步：

1. **定位根因**，先读代码，不猜测
2. **写回归测试**，先写测试复现 bug，再修代码
3. **修代码**，确保新测试通过
4. **调用 safety-reviewer**（参见 [safety-review-policy.md](safety-review-policy.md)）
   - 判断触发类别，传入 diff + 相关文件 + 测试变更 + 风险点
   - C 类变更（纯注释/文档/格式）→ 跳过
   - 收到 BLOCKER → 必须修复后重审，或触发外部升级
5. **更新 CHANGELOG.md** 的 `[Unreleased]` 段，追加一行 `- fix: <描述>`
6. **commit**，message 格式：`fix: <描述> — 补回归测试防止重现`
7. **push**（pre-push hook 自动跑全量测试）
8. **push 后查错误日志**：
   ```bash
   journalctl -u k8s-netlab -p err --since "5 minutes ago" --no-pager
   ```
