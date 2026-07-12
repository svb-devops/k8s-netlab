# LabGen Assetization Rules v0.1

最小版本 — 由外部指令（`Lab-to-Article Sprint Day 1`）首次引用但仓库内此前不存在，按该指令要求创建，与 `.claude/rules/labgen-content-fix.md` 的既有工作流规则保持一致（该规则是本文件的机制化前身，本文件把它推广为跨 sprint 的通用要求）。

## 核心原则

手动修一次 lab draft 的内容错误，只解决这一篇 lab。只有把踩坑经验写回下面六类资产之一，才能防止下一个 lab 重复踩同一个坑。**改草稿内容不算资产化完成。**

## 六类资产及对应文件

| 资产类型 | 写回位置 | 判断标准 |
|---------|---------|---------|
| `generation_patterns` | `backend/labgen/article_lab_prompt_builder.py` 对应领域常量（`_K8S_COMMAND_CONSTRAINTS` / `_LINUX_COMMAND_CONSTRAINTS`） | 这条经验能不能提前写进 prompt，让 LLM 下次生成时就不犯 |
| `generation_anti_patterns` | 同上，明确列出"禁止生成的模式"（如 shell 变量捕获、`kubectl delete namespace`） | 是否是可枚举、可描述的反模式，而非一次性拼写错误 |
| `verifier_patterns` | `backend/labgen/static_validator.py` / `backend/labgen/kubectl_executor.py` / `backend/labgen/linux_command_executor.py` | 这条约束能不能写成机器可执行的校验规则，在发布前拦截，而不依赖 LLM 主动遵守 |
| `rehearsal_checklist` | `RUNBOOK.md` 对应场景，或 `docs/labgen/` 下彩排相关文档 | 这是不是一个人工彩排时应该主动检查的项目 |
| `cleanup_and_vm_lifecycle_lessons` | `RUNBOOK.md`（VM/namespace 生命周期相关场景） | 是否涉及 VM/namespace 创建、清理、幂等性方面的教训 |
| `production_sprint_log` | `docs/labgen/<SPRINT_NAME>_RESULT_v0.1.md` | 记录本次 sprint 的完整过程、决策、遇到的问题，供下次 sprint 参照 |

## 资产化判断标准（复用自 `.claude/rules/labgen-content-fix.md`）

改完草稿内容后，问自己：
- 这个问题是"这篇 lab 特有的内容错误"，还是"生成/校验/彩排流程中的通用性问题"？
- 通用性问题 → 必须写回上表至少一类资产
- 内容特有、下次大概率不会再犯的具体错误 → 改草稿即可，不用写资产，避免过度设计

## 强制要求

1. 每次 sprint 结束前，必须明确列出本次 sprint 触发了哪些资产更新（文件路径 + 变更摘要），没有触发任何资产更新的 sprint 需要说明原因（比如全程零缺陷，纯属罕见）。
2. 资产更新必须对照真实执行器/校验器逻辑核对，不能凭印象写——写错方向比不写还糟。
3. 资产文件的变更需要走正常的 bug-fix / feature 工作流（回归测试 + CHANGELOG + safety-reviewer），不因为是"资产沉淀"就豁免质量门禁。
