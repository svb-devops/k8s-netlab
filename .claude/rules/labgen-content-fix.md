# 触发条件：手动修复 LabGen LLM 生成内容的 bug

适用场景：`article_draft_service` 生成的 lab draft 出现命令跑不通 / verify 类型用错 / patch 路径写错等问题，靠人工改草稿修复。

**铁律：改完草稿内容不算修完。必须先判断这是不是"生成模式"问题——是就要反哺进 prompt，否则下一篇文章原样重犯。**

背景：`bb4fe651`（crashloopbackoff-describe-logs）这篇 lab 从生成到发布花了近一周，绝大部分时间花在人工调试 LLM 生成的 shell 变量语法、`kubectl delete namespace` 这类命令跑不通的问题上。这些问题当时只是改了草稿内容，教训没有写回 `article_lab_prompt_builder.py`，直到用户追问才回头补上。核心认知：**改草稿内容只解决这一篇文章；改 prompt 才是让下一篇文章少踩同一个坑的资产。**

---

## 判断标准

改完草稿内容后，问自己：

- 这个 bug 是"这篇文章特有的内容错误"（比如引用了一个不存在的字段名），还是"LLM 生成时的通用模式性错误"（比如系统性地生成 shell 变量语法、系统性地假设能删 namespace）？
- 如果是**通用模式性错误** → 必须反哺进 prompt，不能只改草稿
- 如果确实是**内容特有的**、下篇文章大概率不会再犯的具体错误 → 改草稿即可，不用改 prompt，避免过度设计

---

## 需要反哺进 prompt 时，按以下步骤

1. **定位约束该加在哪个执行器/校验器上**：K8s 域对照 `backend/labgen/kubectl_executor.py`（`validate_command()`/`_BLOCKED_PATTERNS`/`_BLOCKED_SUBCOMMANDS`/`_ALLOWED_OUTPUT_FORMATS`），Linux 域对照 `backend/labgen/linux_command_executor.py`（`ALLOWED_COMMANDS`/`DENIED_COMMANDS`/`_SHELL_METACHARACTERS`）
2. **在 `backend/labgen/article_lab_prompt_builder.py` 的对应领域常量**（`_K8S_COMMAND_CONSTRAINTS` / `_LINUX_COMMAND_CONSTRAINTS`）追加规则，措辞必须和执行器的真实校验逻辑逐字对照，不能凭印象写——写错方向（该禁的没禁、不该禁的禁了）比不写还糟，等于给 LLM 一个错误的心智模型
3. **补回归测试**（`tests/test_labgen_phase1_soft_launch.py::TestCommandGenerationConstraints`）：断言新约束文本确实出现在对应领域生成的 prompt 里
4. 如果 `StaticValidator` 还没有对应的发布前校验（防止即使 LLM 不听 prompt 也能拦住），一并检查 `backend/labgen/static_validator.py` 的 `commands.executor_compatible`/`commands.rbac_coverage` 等检查是否已覆盖这类问题，没覆盖则视为独立的 bug-fix 任务补上

---

## 不允许

- 只改草稿内容、不判断是否该反哺 prompt，直接 commit
- 反哺进 prompt 时不对照执行器真实逻辑，凭感觉写约束文字
- 为了"以防万一"给不确定是否通用的内容特有 bug 也写进 prompt（过度设计，prompt 会越堆越臃肿失焦）

---

## 下一步

- 判断为通用模式性错误 → 走 [feature.md](feature.md) 流程（TDD + CHANGELOG + safety-reviewer B 类，prompt 文本变更不涉及权限/执行逻辑，通常不构成 A 类）
- 判断为内容特有错误 → 走 [bug-fix.md](bug-fix.md) 正常流程，改完即可，不强制走 prompt 环节
