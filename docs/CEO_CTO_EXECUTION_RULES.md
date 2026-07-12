# CEO/CTO Execution Rules v0.1

最小版本 — 由外部指令（`Lab-to-Article Sprint Day 1`）首次引用但仓库内此前不存在，按该指令要求创建。后续如有更完整版本应替换本文件，保留版本号递增。

## 核心红线

1. **不允许 fake success**：任何交付状态标记（PASS / published / verified / completed）必须对应真实执行过的、可复核的证据（命令输出、测试结果、API 响应、文件 diff）。无法验证的状态一律标记为 `UNVERIFIED` 或 `BLOCKED`，不得省略不报。
2. **不允许 placeholder-as-success**：stub/占位内容（如 `LABGEN_LLM_MODE=fake_only` 生成的模板文本）不得作为最终交付内容对外呈现为"已完成"。占位内容只能作为中间脚手架，必须被人工/真实内容替换后才可进入下一阶段。
3. **不允许 BLOCKER/HIGH/MEDIUM 降级**：安全审查（safety-reviewer / codex review）或静态校验（StaticValidator）报出的严重级别不得由执行者自行下调。BLOCKER/HIGH 必须修复或明确升级给人类决策者；不得以"影响不大"为由跳过。
4. **每次踩坑必须资产化**：调试/踩坑过程中发现的通用性问题（非一次性内容错误），必须沉淀为以下至少一类可复用资产，不能只改一次内容了事：
   - `generation_patterns` / `generation_anti_patterns`（写回 prompt builder）
   - `verifier_patterns`（写回 StaticValidator / executor 校验规则）
   - `rehearsal_checklist`（写回彩排 runbook）
   - `cleanup_and_vm_lifecycle_lessons`（写回 RUNBOOK.md 相关场景）
   - `test`（回归测试，防止同一问题重现）
   - `checklist`（新增/更新到既有 checklist 文档）

## 状态语义

| 状态 | 含义 | 允许条件 |
|------|------|---------|
| `PUBLISHED_WITH_ASSETS` | 完整交付：内容真实、验证通过、资产已沉淀 | 全部子项证据齐全 |
| `IN_PROGRESS` | 部分完成，诚实反映当前实际进度 | 任一子项未完成或受阻时必须使用，不得虚报为完成 |
| `BLOCKED` | 因外部依赖（凭证缺失、权限不足、第三方服务不可用等）无法继续 | 必须附带具体原因、复现方式、解除阻塞所需的最小动作 |
| `EXTERNAL_PUSH_BLOCKED` | 本地交付已完成但外部系统（如 GitHub）不可达 | 仅用于外部推送/发布类阻塞，不得用于掩盖本地工作未完成 |

## 失败分类（用于 rehearsal / 生成失败场景）

- `generation_defect`：LLM/内容生成阶段的问题（prompt 覆盖不足、生成内容违反执行器约束）
- `verifier_defect`：校验/验证逻辑本身有缺陷（漏报、误报）
- `runtime_defect`：真实运行环境问题（VM/K3s/网络/权限），非内容问题

## 交付前自查

- 是否有任何一步的"成功"结论没有对应的真实命令输出/测试结果作为证据？
- 是否有 stub/占位内容被当作最终交付内容呈现？
- 是否有已知的 BLOCKER/HIGH 被跳过或降级？
- 本次踩坑是否已经写回对应的资产文件，还是只改了这一次的内容？
