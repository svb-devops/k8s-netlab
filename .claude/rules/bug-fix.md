# 触发条件：修 bug、定位问题、复现错误

每次必须完整执行，不得跳步：

1. **定位根因**，先读代码，不猜测
2. **写回归测试**，先写测试复现 bug，再修代码
3. **修代码**，确保新测试通过
4. **更新 CHANGELOG.md** 的 `[Unreleased]` 段，追加一行 `- fix: <描述>`
5. **commit**，message 格式：`fix: <描述> — 补回归测试防止重现`
6. **push**（pre-push hook 自动跑全量测试）
7. **push 后查错误日志**：
   ```bash
   journalctl -u k8s-netlab -p err --since "5 minutes ago" --no-pager
   ```
