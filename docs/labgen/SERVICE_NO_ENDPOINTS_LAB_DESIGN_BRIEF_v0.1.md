# Lab Design Brief — Service 无 Endpoints v0.1

## 状态

`documentation_only`。本文档是 `SERVICE_NO_ENDPOINTS_LAB_DESIGN_CONTRACT_v0.1.md`（已在生产 sprint 中产出、已通过 rehearsal 验证）的读者向摘要，供 article gate 决策使用，不重复其详细设计推导过程，也不改变已发布 lab 的任何字段。

## 摘要

| 项 | 值 |
|---|---|
| lab_id | `2dcc7b1f-a52f-4a8f-9e8a-3ee9ff0a5a86` |
| target_domain | k8s |
| runtime | dedicated_vm（单命名空间，复用 K3s） |
| 步骤数 | 7 |
| publish_status | published（internal，不在白名单） |
| rehearsal 结果 | PASS（session `3bc6a420-2000-425b-bca3-398d56113dc2`，7/7 步骤，VM 299，K3s v1.34.4） |
| learner smoke 结果 | PASS（session `4aa8175d-4eaa-48f0-a1f8-a4c297e84df5`，session_type=learner，7/7 步骤 + complete() 成功） |
| cleanup_verified | true（两次会话均确认） |

## 真实排查步骤对照文章大纲（读者视角）

1. 部署一个 Deployment + 一个"看似正常"的 Service（selector 默认值与 Pod 实际标签不一致）
2. 观察 `kubectl get endpoints` 为空 —— 这是本 lab 的核心症状锚点
3. `kubectl describe service` 读出 Service 认为的 selector
4. `kubectl get pods --show-labels` 读出 Pod 真实标签，两者对比出根因
5. 用 `kubectl delete` + `kubectl expose` 重建正确的 Service（而非手动 patch selector）
6. 复查 Endpoints 已填充，确认修复生效
7. 清理

## 真实修复路径（非编造）—— 为什么不用 patch

学员 RBAC 未授予 `services` 资源的 `update`/`patch` verb，这是本 sprint 经过 8 轮安全审查后的架构决策（详见 Design Contract 第 40-46 行），并非本文档临时编的教学理由。修复步骤据此设计为 delete+expose，这个约束是真实存在于生产环境的，文章内容必须如实反映这个修复路径，不能为了"看起来更专业"而在文章里描述一个学员实际执行不了的 patch 命令。

## 未解决的已知缺口（诚实标注，不隐藏）

`service_has_endpoints` verify 原语不存在，Endpoints 从空到非空这一核心症状/修复结果目前只能靠学生肉眼 observe，无法被 verifier 机器化断言（第 6 步的 verify 挂在 `service_exists` + `pod_ready` 上，只能间接佐证，不是直接断言 Endpoints 内容）。这个缺口已写入 Design Contract 的 Known Gap 章节，本次不新增该原语。

## Article Gate 判断依据

文章正文的"诊断步骤"部分必须逐条对照上表的 7 个真实步骤撰写，不允许编造未在 rehearsal 中出现过的排查动作（例如不能写"检查 NetworkPolicy"，因为这个 lab 场景里从未涉及 NetworkPolicy）。是否满足这一要求由 `SERVICE_NO_ENDPOINTS_OFFICIAL_ARTICLE_DRAFT_v0.1.md` 的内容自证。
