# 触发条件：加新功能、实现需求

## 必须做的 4 件事（机械门禁会检查）

### 1. 新模块或跨边界设计时，先锁定架构
触发条件（满足任一）：新增 router / service / 独立模块、改动涉及 2 个以上系统边界、引入新的数据流。

> **建议**：跑 `/plan-eng-review` 与用户确认方向，结论写入 ARCHITECTURE.md。
> 不是强制，但跳过的代价是架构腐烂从第一天开始。

### 2. 先写测试（TDD），让测试先 fail，再实现功能
覆盖率门禁（`--cov-fail-under=90`）会在 push 时自动阻断。

### 3. 更新 CHANGELOG.md 的 `[Unreleased]` 段
追加一行 `- feat: <描述>`

**pre-commit hook 会检查**：有代码文件变更但 CHANGELOG 未更新 → 阻断 commit。

### 4. commit + push
pre-push hook 自动跑：8 项安全扫描 + pytest 全量 + Codex（quota 激活后）。

---

## 延伸（建议，非强制）

- **safety-reviewer**（A/B 类变更）：参见 [safety-review-policy.md](safety-review-policy.md)
- **codex review**（quota 激活后）：`codex review --base main`，发现 BLOCKER 必须修复
- **写入知识库**：功能有跨项目复用价值时 → `/root/kb/`
