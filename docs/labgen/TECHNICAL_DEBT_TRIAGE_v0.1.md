# Technical Debt Triage v0.1

## 状态

`documentation_only`。仅分类，本次不修复任何一项。

---

## 1. 26 个 xfailed demo_seed Job verifier/manifest 问题

```
status: backlog
reason: >
  generation_templates.py 的 PYTHON_BASICS/HTTP_API_BASICS/DATA_TRANSFORM_BASICS
  三个模板使用了 verifier 从未实现的 JOB_COMPLETED/POD_READY 类型，且引用不存在的
  manifests/*.yaml 文件。这是本次 sprint 新增的 verify.type_implemented 校验意外
  发现的预置缺陷，非本次改动引入。彻底修复需要给 KubernetesApiFactory 增加
  BatchV1Api（会牵动另外 2 个测试文件的 2-tuple 签名约定）+ verifier 的 ClusterRole
  RBAC 扩展，或者重写 3 个模板的 9 个步骤内容——工作量超出"文档梳理 + 回归检查"
  这次任务的范围，且这 3 个模板当前本来就不在任何已发布 lab 的路径上（只在
  demo_seed/generation 测试里被引用），不修复不影响生产可用性。
risk: low
recommended_next_task: >
  独立立项："demo_seed 模板 verify 能力补齐"，作为一个单独的 feature sprint，
  在 KubernetesApiFactory 签名变更前先跑一次 /plan-eng-review 评估影响面。
```

## 2. `service_has_endpoints` verifier 是否需要补齐

```
status: backlog
reason: >
  Service-no-Endpoints lab 的核心症状（Endpoints 从空到非空）目前只能通过学生
  observe 环节人工确认，无法被 verifier 机器化断言（详见
  SERVICE_NO_ENDPOINTS_LAB_DESIGN_CONTRACT_v0.1.md 的 Known Gap 章节）。这不影响
  该 lab 当前的 internal-only 状态，但会成为"是否可以对真实学生开放"这个决策的
  一个实质性质量门——没有机器化验证，学生可能"看起来完成了"但实际没理解，或者
  卡在第 6 步无法确定自己是否做对。
risk: medium
recommended_next_task: >
  在 LABGEN_CONTROLLED_INVITE_POLICY_v0.1.md 的 go/no-go checklist 中已列为前置
  条件之一。建议在决定重启该 lab 的邀测前，作为独立 bug-fix/feature 任务补齐
  VerifyType.SERVICE_HAS_ENDPOINTS（检查 Service 对应 Endpoints 对象的 .subsets
  是否非空），走 feature.md 标准流程（TDD + CHANGELOG + safety-reviewer B 类）。
```

## 3. kubectl_executor / static_validator 存在固定下标解析重复

```
status: backlog
reason: >
  本次 8 轮安全审查过程中，_check_service_type_escalation 等函数各自用 shlex
  parts 数组做 token 扫描，与 kubectl_executor.py 里其他历史检查函数
  （如 _check_output_format）逻辑模式相似但没有抽象成公共的 "flag/positional
  token scanner" 工具函数，存在轻微重复。当前每处都已各自验证正确（8 轮审查
  确认无绕过），重复本身不构成安全风险，只是可维护性话题。
risk: low
recommended_next_task: >
  下次触碰 kubectl_executor.py 做 refactor 时（走 refactor.md 流程，先写测试
  证明旧行为），顺手把 token 扫描逻辑收敛成一个共享 helper，不必单独立项。
```

## 4. `_BLOCKED_SUBCOMMANDS` 是黑名单而非白名单

```
status: backlog
reason: >
  第 8 轮安全审查确认的架构性观察：当前 kubectl 子命令过滤是"枚举已知危险子
  命令并拒绝"（黑名单），理论上比"只允许已知安全子命令通过"（白名单）更容易
  被新增的 kubectl 版本/插件子命令绕过。但截至本次审查，未发现任何具体可利用
  的绕过路径（不是"已知有洞"，是"架构模式本身不是最优"）。学员 RBAC 权限本身
  也是防线之一（即使命令通过了字符串过滤，K8s API Server 仍会因权限不足拒绝）。
risk: low
recommended_next_task: >
  不构成当前的紧急项。建议在下一次对 kubectl_executor.py 做大改动时，评估转
  白名单子命令集的成本（需要枚举当前所有 lab 实际使用到的子命令，逐一确认不
  遗漏），作为独立技术债 sprint 处理，不需要现在动。
```

---

## 汇总

| # | 项目 | status | risk |
|---|------|--------|------|
| 1 | 26 xfailed demo_seed | backlog | low |
| 2 | service_has_endpoints verifier | backlog | medium |
| 3 | executor/validator 解析重复 | backlog | low |
| 4 | 黑名单 vs 白名单子命令 | backlog | low |

无 `fix_now` 项——四项均评估为可以延后处理，且延后不影响当前两个已发布 lab 的 internal-only 安全性与正确性。#2 是四项里唯一有明确触发时点（邀测重启前）的一项，已写入 Invite Policy 的 go/no-go checklist。
