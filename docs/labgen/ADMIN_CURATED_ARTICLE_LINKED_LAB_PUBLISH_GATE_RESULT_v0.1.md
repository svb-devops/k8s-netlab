# Admin-curated Article-linked Lab Publish Gate v0.1 — RESULT

**Status**: PUBLISH_GATE_READY  
**Date**: 2026-06-21  
**Executed by**: Claude Sonnet 4.6 + smoke-admin  

---

## A. 目标

为 article-to-lab pipeline 增加 rehearsal gate，确保：
1. 经 pipeline 生成的 LabDraft 在发布前必须完成内部预演（INTERNAL_REHEARSAL）
2. 预演通过后 `rehearsal_completed=True`，publish gate 解锁
3. 普通 LEARNER session 的 step check 安全性不受影响

---

## B. 代码变更

### B.1 新字段（models.py）
```python
rehearsal_required: bool = False   # 文章 pipeline 生成时设为 True
rehearsal_completed: bool = False  # rehearsal 成功完成后设为 True
```

### B.2 PublishDecisionService rehearsal gate（publish_decision.py）
- `evaluate()` 在 StaticValidator 之前检查 rehearsal gate
- `PublishBlockReasonCode.REHEARSAL_REQUIRED` 新增 block code
- HTTP 409 with REHEARSAL_REQUIRED 代码

### B.3 PublishService defense-in-depth（publish_service.py）
- `RehearsalNotCompleted` 异常类
- `publish()` 入口处检查 rehearsal gate（无论调用路径）

### B.4 StepProgressionService rehearsal bypass（step_progression_service.py）
- INTERNAL_REHEARSAL session 允许检查 DRAFT 状态的 lab
- LEARNER session 仍必须要求 PUBLISHED（安全不变量保留）

### B.5 _do_cleanup 设置 rehearsal_completed（lab_session_service.py）
- 仅当 `session_type=INTERNAL_REHEARSAL` 且 `ready_to_complete=True` 时
- 设置 `draft.rehearsal_completed=True`

---

## C. 生产执行记录

### C.1 Article Draft → LabDraft
- article_draft_id: `aa7c4a99-64a6-405d-bdb6-a4765b105b6d`
- lab_draft_id: `cf019133-3a50-444d-8870-a84c25391cb7`
- `rehearsal_required=True`，`publish_status=draft`

### C.2 Publish gate 验证（rehearsal 前）
```
POST /api/labgen/drafts/cf019133.../publish → 409 REHEARSAL_REQUIRED
```

### C.3 Rehearsal 执行
- session_id: `0b0fb49b-0c84-41e6-abee-5d56ffb41df4`
- vm_id: 401 (labgen-home-k3s-staging-01)
- namespace: `lab-0b0fb49b-0c84-41e6-abee-5d56ffb41df4`

**K3s kubeconfig 修正**：
- platform kubeconfig（`/etc/labgen/home_lab_mvp.kubeconfig`）：旧 IP → 新 IP
- verifier kubeconfig（`/var/lib/labgen-staging/verifier-credentials/401/kubeconfig.yaml`）：旧 IP → 新 IP

**步骤执行**：
- step_1（configmap_exists，name=app-config）→ PASS（手动创建 ConfigMap）
- step_2（namespace_exists）→ PASS（namespace 自动存在）
- `ready_to_complete=True`

**完成**：
```
POST /internal/rehearsal-sessions/0b0fb49b.../complete
→ status=LAB_CLOSED, cleanup_verified=True
```

**验证**：
```
GET /api/labgen/drafts/cf019133...
→ rehearsal_completed=True
```

### C.4 发布
```
POST /api/labgen/drafts/cf019133.../publish
→ publish_status=published
```

### C.5 Catalog 验证
```
GET /api/labs
→ 5 labs (4 existing + 1 article-linked)
```

| # | lab_id | title |
|---|--------|-------|
| 1 | 67fca5e4 | Kubernetes Basics: Your Isolated Lab Environment |
| 2 | b0b97742 | Kubernetes ConfigMap Basics |
| 3 | d9f44383 | Kubernetes Secret Basics |
| 4 | e52b8b80 | Kubernetes Deployment Basics |
| 5 | cf019133 | Untitled Lab (from article) ← **new** |

---

## D. 测试结果

- 30 tests in `tests/test_labgen_article_publish_gate.py` — all PASS
- 新增 2 个回归测试：
  - `test_internal_rehearsal_step_check_allowed_on_draft_lab`
  - `test_learner_session_cannot_check_steps_on_draft_lab`
- 修复 pre-existing failure: `test_adapter_status_production_safe_false_in_test_mode`
- **全量**：3632 passed，0 failed，93%+ coverage

---

## E. Safety 不变量（全部保留）

- 不可用 live LLM ✅（evaluated_by=STUB）
- 不开放普通用户 article upload ✅（admin-only）
- 不自动发布未经 rehearsal 的 generated lab ✅（gate 双重防护）
- 不修改 production VMID 500-599 ✅
- 不保留/持久化 raw article text ✅
- 不记录 kubeconfig/token/credential 到日志 ✅
- LEARNER session 仍不能检查 DRAFT labs ✅（safety 回归测试覆盖）

---

## F. 未解决 / 后续

- lab title 为 "Untitled Lab (from article)" — article pipeline stub 不生成真实标题，需 LLM 实现后改进
- step verify template 含 `manual_review_required=True` — 需后续设计 admin manual review flow
- 5th lab 的 lab content 来自 stub contract，不是真实 K8s 教学内容
