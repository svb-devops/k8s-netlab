# 触发条件：所有涉及代码变更的操作

## 分级规则

### A 类 — 强制审查，硬失败阻断

触发条件（任一满足）：
- Proxmox VM 操作：create / delete / purge / reclaim / reconcile
- auth / ownership / permission 逻辑变更
- shell 命令构造（注入风险）
- CSP 规则变更 / 前端 DOM 注入路径
- asyncio event loop 或 executor 相关代码
- tracker / Proxmox 状态同步逻辑

### B 类 — 常规审查，软失败可降级

触发条件：所有其他代码逻辑变更，包括：
- 新 feature、bug fix、refactor
- 新 API endpoint
- 测试基础设施修改

### C 类 — 豁免，不触发

- 文档、注释
- 纯样式调整
- 无逻辑变化的 rename
- 机械格式化

---

## 外部升级条件（Codex CLI 第二审）

出现以下任一情况，强制升级外部审查：

1. A 类变更
2. 单次变更同时跨越 3 个以上系统边界（API + tracker + Proxmox client + 前端控制流等）
3. 安全模型变更（ownership 规则、token/session 生命周期、权限校验、跨用户资源访问）
4. **BLOCKER disagreement**：safety-reviewer 报出 BLOCKER，main agent 判断可忽略 → 强制升级，不得绕过

条件 4 是客观可观察事实（报告分歧），不依赖主观判断。

当前阶段 Codex CLI 未安装时，升级动作 = 告知用户、列出 BLOCKER 内容、等待确认，不得自行继续。

---

## main agent 约束

调用 safety-reviewer 时：
- 只传 diff、相关文件、测试变更、风险点标注
- 不传"我为什么这么实现"的解释
- 不对审查结论预先辩护
- 收到 BLOCKER 后不得自行忽略（必须修复后重审，或触发外部升级）
