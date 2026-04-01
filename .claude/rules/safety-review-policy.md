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

## 双层审查体系

### 第一层：safety-reviewer（Claude，每次 A/B 类变更）
同一模型审查，擅长架构推理和安全隐患，但存在自审盲区。

### 第二层：Codex（OpenAI gpt-5.3-codex，每次提交前）
不同公司、不同训练数据、真正独立。擅长发现反模式（隐式类型转换、不一致错误处理、玩具代码）。
两者都通过 = 信号收敛，可信度最高。

**调用方式**：
```bash
codex review --base main
```
已集成到 pre-push hook（有 BLOCKER 自动阻断推送）。
feature.md / bug-fix.md 中列为提交前必跑步骤。

### Codex 强制升级条件（原"外部升级"）
出现以下任一情况，Codex review 不可跳过：

1. A 类变更（VM 操作 / auth / shell 注入路径）
2. 单次变更跨越 3 个以上系统边界
3. 安全模型变更（ownership / token / session / 权限校验）
4. **BLOCKER disagreement**：safety-reviewer 报 BLOCKER，main agent 认为可忽略 → 强制等 Codex 第二意见

条件 4 是客观事实（两个 agent 分歧），不依赖主观判断，不得绕过。

**quota/auth 失败时的处理**：
- B 类变更：pre-push hook 打印警告后跳过，不阻断 push
- 满足上述强制升级条件之一：main agent 必须人工确认后才能继续，不得自行放行

---

## main agent 约束

调用 safety-reviewer 时：
- 只传 diff、相关文件、测试变更、风险点标注
- 不传"我为什么这么实现"的解释
- 不对审查结论预先辩护
- 收到 BLOCKER 后不得自行忽略（必须修复后重审，或触发外部升级）
