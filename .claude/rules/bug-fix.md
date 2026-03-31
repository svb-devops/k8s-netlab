# 触发条件：修 bug、定位问题、复现错误

## 必须做的 3 件事（机械门禁会检查）

### 1. 定位根因，先读代码，不猜测
### 2. 先写回归测试复现 bug，再修代码
覆盖率门禁（`--cov-fail-under=90`）会在 push 时自动阻断。

### 3. 更新 CHANGELOG.md 的 `[Unreleased]` 段
追加一行 `- fix: <描述>`

**pre-commit hook 会检查**：有代码文件变更但 CHANGELOG 未更新 → 阻断 commit。

---

### 4. 调用 safety-reviewer（A/B 类变更必须，C 类豁免）

- **A 类**（硬阻断）：auth / VM 操作 / shell 命令构造 / CSP / asyncio / tracker 变更
- **B 类**（常规审查）：其他 bugfix / 新 endpoint / 测试基础设施
- **C 类**（豁免）：纯文档 / 注释 / 格式

详见 [safety-review-policy.md](safety-review-policy.md)，收到 BLOCKER 不得自行忽略。

---

commit message 格式：`fix: <描述> — 补回归测试防止重现`

push 后 pre-push hook 自动跑：8 项安全扫描 + pytest 全量。

---

## 延伸（建议，非强制）

- **codex review**（quota 激活后）：`codex review --base main`，发现 BLOCKER 必须修复
- **push 后查错误日志**：`journalctl -u k8s-netlab -p err --since "5 minutes ago" --no-pager`
