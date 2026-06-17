# Small Customer Pilot Result v0.1

**Date**: 2026-06-16  
**Operator**: Claude Code (senior dev + ops)  
**Decision**: SMALL_CUSTOMER_PILOT_BLOCKED  
**Blocker**: NO_SUITABLE_SMALL_CUSTOMER  

---

## A. Executive Summary

| Item | Value |
|------|-------|
| Customer count | 0（未识别） |
| Learner count | 0 |
| Labs attempted | 0 |
| Labs completed | 0 |
| Sessions completed | 0 |
| Final decision | **SMALL_CUSTOMER_PILOT_BLOCKED** |
| Blocker | NO_SUITABLE_SMALL_CUSTOMER |
| K8s domain proof validated | N/A — pilot not executed |
| Supports Article-to-Lab pipeline design gate | **Conditionally yes** — system is technically ready；需在小客户确定后执行 |

Pre-Pilot Gate 系统检查全部通过。系统健康，4 个 K8s Labs 已发布，无运行残留，安全状态清洁。阻断原因唯一：在任务执行时，没有满足 Section 四标准的外部客户或可信小团队被识别、承诺并纳入 onboarding 流程。

---

## B. North Star Alignment

- **"读完即练，结果说话"**：系统能力已就绪；pilot 未执行不代表能力缺失
- **K8s 仍为 domain proof**：未宣称任何文章到实验的自动转化已完成
- **Article-to-Lab 路径**：保持开放；本次 BLOCKED 不影响下一阶段设计
- **Linux / 多领域迁移能力**：未破坏；home_lab_mvp 可移植性完整
- **未声明 HA / production ready / public launch**：✓

---

## C. Customer Profile

**状态：未识别**

执行时间点（2026-06-16），系统中 28 个注册用户全部为测试/开发账号：

| 账号类型 | 账号 | 状态 |
|---------|------|------|
| 内部测试 | k8s_test, alice, k8s_test01–05 | 测试账号 |
| 容量测试 | capacitytest | 测试账号 |
| 烟雾测试 | smoke-user-01, smoke-admin | 测试账号 |
| 批量 pilot 账号 | pilot-user-01 ~ pilot-user-08 | 测试账号，非外部客户 |
| 批量 cohort 账号 | cohort-user-A/B/C | 测试账号 |
| Round 2 learners | learner-r2-a, learner-r2-b | 内部验证参与者 |
| 其他 | jaj, haha, jayjay, limao, zhr | 测试账号 |

以上账号均不满足 Section 四客户标准：
- 无外部联系人正式确认 early MVP 边界
- 无正式承诺无 SLA / 预约制 / sequential only
- 无客户联系人确认反馈意愿
- Round 2 learners 为内部受控测试参与者，不构成"外部小客户"

**判定**：NO_SUITABLE_SMALL_CUSTOMER — pilot 不可启动。

---

## D. Per-Learner Results

不适用（pilot 未执行）。

---

## E. Lab-Level Findings（Pre-Pilot Gate 观察）

4 个 Published Labs 状态正常：

| Lab | Lab ID | 状态 |
|-----|--------|------|
| Kubernetes Basics: Your Isolated Lab Environment | 67fca5e4 | published ✓ |
| Kubernetes ConfigMap Basics | b0b97742 | published ✓ |
| Kubernetes Secret Basics | d9f44383 | published ✓ |
| Kubernetes Deployment Basics | e52b8b80 | published ✓ |

**附加发现**：repository 中存在 356 个状态为 draft 的 "Python Variables and Control Flow" 草稿（创建于 2026-06-10）。这些草稿由开发测试阶段的 stub generator 生成，均为 draft 状态，不对用户可见，不影响 catalog。但草稿数量远超预期，应在下一阶段前清理，防止 Admin 界面混乱。

---

## F. Ops Findings（Pre-Pilot Gate 系统检查）

### F.1 系统健康

| 检查项 | 结果 | 备注 |
|--------|------|------|
| Backend health | ✅ PASS | `{"status":"healthy","proxmox":{"connected":true}}` |
| Cloudflare Tunnel | ✅ PASS | active |
| VM 401 | ✅ PASS | status: running |
| K3s node | ✅ PASS | k8s-template Ready control-plane v1.34.4+k3s1 |
| Published labs | ✅ PASS | 4 个，与预期完全一致 |
| Unpublished labs visible | ✅ PASS | 356 drafts 均为 draft 状态，不对用户暴露 |

### F.2 残留检查

| 检查项 | 结果 | 备注 |
|--------|------|------|
| Active sessions（LAB_ACTIVE 状态） | ✅ 0 | |
| lab-* namespaces | ✅ 0 | kubectl get namespaces 确认 |
| RoleBinding residuals | ✅ 0 | kubectl get rolebindings -A 确认 |
| lab-learner SA residuals | ✅ 0 | |
| Tainted VMs | ✅ 0 | data/tainted_vms.json = {} |
| Learner kubeconfig residuals | ✅ 0 | /var/lib/labgen-staging/learner-kubeconfigs/ 为空 |
| Deployment/ReplicaSet/Pod residuals | ✅ 0 | kubectl get pods -A 无 lab 相关 pod |

### F.3 需关注项（非阻断）

| 项目 | 严重级 | 详情 |
|------|--------|------|
| LAB_START_FAILED 残留 session | NOTE | session_id=b0ca4036，user=k8s_test，状态=LAB_START_FAILED，failure_reason=namespace_create_failed，cleanup_verified=False。K3s 上无对应 namespace，无实际运行残留。属开发测试期陈旧记录。 |
| VM 401 owner = learner-r2-b | 需操作 | 新学员 session 前须执行 §K.3 所有权转移 |
| lab-verifier ClusterRole | NOTE | K3s 上当前无 lab-verifier ClusterRole。属于预期状态（无活跃 session 时不存在），verifier re-init 会重建。需确认 re-init 流程。 |
| 356 个 Python 草稿 | NOTE | 2026-06-10 开发测试产生，stub 生成非 LLM，全部 draft，Admin 界面噪声大 |

### F.4 Runbook §K 可用性

Runbook §K（VM Ownership / Learner Assignment Precheck）已就绪，从未在真实外部客户场景下验证过。这是 Small Customer Pilot 需要验证的核心 ops 能力之一。

---

## G. Security Findings（Pre-Pilot Gate）

| 检查项 | 结果 |
|--------|------|
| kubeconfig 泄露 | ✅ 无 |
| verifier credential 泄露 | ✅ 无 |
| learner credential 泄露 | ✅ 无（/var/lib/labgen-staging 为空） |
| Secret value/base64 泄露 | ✅ 无 |
| 跨 namespace 访问 | ✅ 无（当前无任何 lab namespace） |
| production VMID 500-599 | ✅ 未触碰 |
| LLM 调用 | ✅ 未启用 |
| ClusterRoleBinding | ✅ 无 lab 相关 CRB |
| 356 Python 草稿是否含敏感信息 | 待确认（stub 生成，内容应为占位符，但建议清理） |

---

## H. Product Findings

不适用（pilot 未执行）。

---

## I. Issue Triage

| ID | Severity | Dimension | 描述 |
|----|----------|-----------|------|
| I-01 | BLOCKER | customer fit | 无外部客户识别，pilot 无法启动 |
| I-02 | NOTE | ops | LAB_START_FAILED 陈旧记录（k8s_test），cleanup_verified=False，K3s 无残留 |
| I-03 | NOTE | ops | 356 个 Python 草稿污染 Admin UI，建议执行批量清理 |
| I-04 | NOTE | ops | VM 401 owner 仍为 learner-r2-b，需 §K.3 转移后方可给新学员 |
| I-05 | NOTE | ops | lab-verifier ClusterRole 当前不存在（预期状态，re-init 重建） |

---

## J. Final Decision

**SMALL_CUSTOMER_PILOT_BLOCKED**

**主要阻断原因**：NO_SUITABLE_SMALL_CUSTOMER

在本次执行时间点，系统技术层面完全就绪（Pre-Pilot Gate 全部系统检查通过），但满足 Section 四标准的外部客户或可信小团队尚未被识别、承诺和正式纳入 onboarding 流程。

依据规范：`如果没有合适客户：不可启动 pilot session，final decision: SMALL_CUSTOMER_PILOT_BLOCKED`

本决定是 fail-closed 的正确执行，不是系统失败。系统已准备好，等待客户就位。

---

## K. Recommendation

**推荐下一步**：在识别合适客户后，立即执行 Small Customer Pilot

当有满足以下条件的客户确认时，可无需重新执行 Pre-Pilot Gate（除非超过 2 周）：

**客户就绪标准**：
1. 真人 / 可信小团队（非内部测试账号）
2. 客户联系人书面确认接受 early MVP 边界（Section 七 全部条款）
3. 2-3 名学员，具备基本命令行能力
4. 愿意按照预约制、sequential only 参与
5. 愿意提供完整 Section 十一反馈

**就绪后立即执行**（按 Runbook §J.2 + §K）：
1. 创建学员账号
2. 执行 §K.3 VM 401 ownership 转移
3. 执行 §J.2 全量 pre-cohort precheck（10 项）
4. 发送 Section 七 onboarding notice，收到确认
5. 每个 lab session 前 re-init verifier
6. 监督 session，收集 Section 十一反馈
7. 完成后更新本文档

**并行可做**（不依赖客户就绪）：
- 清理 356 个 Python draft 草稿（Admin UI 噪声）
- 清理 k8s_test 的 LAB_START_FAILED 陈旧 session 记录
- 讨论 Article-to-Lab Pipeline Design Gate 时间表

**不推荐**：
- 在无外部客户的情况下使用内部账号模拟 pilot（违反无伪造规则）
- 将 Round 2 learners 降级重用为 small customer（性质不同）

---

## L. Technical Self-Check

- 无 TODO/FIXME ✓
- 无 placeholder-as-success ✓
- 无伪造 customer feedback ✓
- 无伪造 learner feedback ✓
- 无 API-only simulation 替代 frontend ✓
- 无 operator shell 替代 learner terminal ✓
- 无 production VM / pool / registry 被修改 ✓
- 无 LLM 调用 ✓
- 未发布第五个 lab ✓
- 未提高并发 ✓
- 未宣称 public launch ✓
- 未宣称 production ready ✓
- 未宣称 arbitrary Article-to-Lab 已完成 ✓
- 未将 small customer pilot 等同 public launch ✓
- 未将 home_lab_mvp 等同 HA production ✓

---

## M. Modified Files

| 文件 | 操作 |
|------|------|
| `docs/labgen/SMALL_CUSTOMER_PILOT_RESULT_v0.1.md` | 新建（本文件） |
| `deploy/labgen/staging_ops_ticket_status.md` | 更新（新增 G-22） |
| `deploy/labgen/staging_infrastructure_checklist.md` | 更新（新增 Pilot Execution） |
| `CHANGELOG.md` | 更新 |

---

## N. Deliverables

- Result artifact: `docs/labgen/SMALL_CUSTOMER_PILOT_RESULT_v0.1.md` ✓
- Pre-Pilot Gate system checks: 全部通过 ✓
- Customer assessment: BLOCKED — NO_SUITABLE_SMALL_CUSTOMER ✓
- Status files updated ✓
- No code changes (docs + status only) ✓

---

*Executed by Claude Code (senior dev + ops) — 2026-06-16*  
*Role: operator-supervised, docs-only execution*
