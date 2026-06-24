# Existing Lab Template Extraction v0.1

**Date**: 2026-06-24
**Operator**: Claude Code acting as senior dev + ops
**Status**: Authoritative template reference — derived from 6 verified published labs
**No real secrets in this document.**

---

## Purpose

这 6 个 published labs 不是临时 demo 或弃用的实验作品。它们是：

> **Phase 1 Admin-curated Article-to-Lab 的标准模板资产。**

所有后续新实验必须复用此结构，不得发明新格式，不得偏离此 schema。

---

## Published Labs Inventory（截至 2026-06-24）

| Lab ID (前8位) | Title | Domain | Steps | Duration | Verified |
|---------------|-------|--------|-------|----------|---------|
| 67fca5e4 | Kubernetes Basics: Your Isolated Lab Environment | K8s | 1 | 10min | ✅ G-34 real learner |
| b0b97742 | Kubernetes ConfigMap Basics: Store Your First Config | K8s | 2 | 15min | ✅ G-34 real learner |
| d9f44383 | Kubernetes Secret Basics: Protect Your First Configuration | K8s | 2 | 15min | ✅ G-34 real learner |
| e52b8b80 | Kubernetes Deployment Basics: Run Your First Workload | K8s | 2 | 20min | ✅ G-34 real learner |
| cf019133 | Kubernetes ConfigMap 实战：从文章到实验 | K8s | 2 | 30min | ✅ G-47 CTA dry run |
| 6c439064 | Linux Files and Permissions Basics | Linux | 4 | 20min | ✅ G-51 trusted reader |

---

## Common LabDraft Fields（所有 domain 通用）

```json
{
  "schema_version": "1.0",
  "lab_id": "<uuid>",
  "source_article_id": "<internal-id>",      // NOT exposed to learner API
  "title": "...",
  "description": "...",
  "estimated_duration_minutes": 20,
  "prerequisites": ["..."],
  "target_domain": "linux" | null,            // null = K8s
  "runtime_requirements": { ... },
  "steps": [...],
  "cleanup": { ... } | null,
  "linux_sandbox_policy": { ... } | null,
  "linux_cleanup": { ... } | null,
  "image_resolution": [...],
  "pollution_level": "none" | "low" | "medium" | "high",
  "shared_namespace_candidate": false,
  "publish_status": "published",
  "validator_results": [...],
  "rehearsal_required": true,
  "rehearsal_completed": true,
  "ai_tutor_context": "...",
  "experiment_background": "...",             // OPEN: empty in some labs
  "completion_summary": "...",               // OPEN: empty in some labs
  "created_at": "...",
  "updated_at": "..."
}
```

**注意缺失字段（均为 P0/P1 Gap）**：
- `article_url`: 无此字段。P0 Gap。
- `cta_copy`: 无此字段。P0 Gap。
- `email` 在用户模型中：P1 Gap（与 lab schema 无关，但与 reader flow 相关）。

---

## K8s Lab Step Schema（标准 K8s domain 步骤）

每个 step 包含以下字段：

```json
{
  "schema_version": "1.0",
  "step_id": "<uuid>",
  "order": 1,
  "why": "为什么做这一步（学习动机、概念背景）",
  "do": "做什么（操作目标描述）",
  "commands": [
    {
      "command": "kubectl get namespace",
      "description": "列出当前 namespace",
      "expected_output": "NAME   STATUS   AGE\n..."
    }
  ],
  "observe": "观察到的输出说明",
  "explain": "背后的原理解释",
  "verify": [
    {
      "schema_version": "1.0",
      "verify_id": "<uuid>",
      "type": "namespace_exists" | "secret_exists" | "configmap_exists" | ...,
      "namespace": "{{lab_namespace}}",
      "name": "my-resource",
      "label_selector": null,
      "cluster_scope": false,
      "supported_runtimes": ["k8s"],
      "blocking_level_on_fail": "hard" | "soft",
      "manual_review_required": false,
      "notes": "..."
    }
  ]
}
```

**K8s 验证类型（已实现）**:
- `namespace_exists` — 验证 namespace 存在
- `configmap_exists` — 验证 ConfigMap 存在
- `secret_exists` — 使用 list（field_selector）验证，不读 data
- `deployment_exists` — 验证 Deployment 存在
- `pod_running` — 验证 Pod 处于 Running 状态

---

## Linux Lab Step Schema（Linux domain 附加字段）

Linux lab 步骤在 K8s 基础上新增：

```json
{
  "schema_version": "1.0",
  "step_id": "<uuid>",
  "order": 1,
  "why": "...",
  "do": "...",
  "commands": [...],
  "observe": "...",
  "explain": {
    "concept": "核心概念解释",
    "observation": "预期观察说明",
    "confidence": "high" | "medium" | "low",
    "admin_verified": true,
    "published_to_student": true
  },
  "verify": [],                              // Linux domain 通常为空列表
  "linux_verify": [
    {
      "verify_id": "<uuid>",
      "type": "file_exists" | "file_content_contains" | "permission_octal" | ...,
      "path": "/tmp/labgen-linux-sandboxes/{{session_id}}/...",
      "expected": "...",
      "blocking_level_on_fail": "hard" | "soft"
    }
  ],
  "troubleshoot": "如果步骤失败，常见原因和解决方法"
}
```

**Linux 验证类型（已实现）**:
- `file_exists` — 验证文件是否存在
- `file_content_contains` — 验证文件内容包含预期字符串
- `permission_octal` — 验证文件权限（stat 输出）

---

## Content Quality Observations（模板资产现状）

| 字段 | K8s Labs (5个) | Linux Lab (1个) | 说明 |
|------|---------------|----------------|------|
| `title` | ✅ 完整 | ✅ 完整 | 所有 6 个 lab 均有 |
| `description` | ✅ 完整 | ✅ 完整 | 所有 6 个 lab 均有 |
| `estimated_duration_minutes` | ✅ 有值 | ✅ 有值 | 10-30min |
| `prerequisites` | ✅ 完整（部分为空列表） | ✅ 完整 | — |
| `experiment_background` | ❌ 字段缺失 | ✅ 有内容 | MEDIUM-001: K8s labs 缺此字段 |
| `completion_summary` | ❌ 字段缺失 | ✅ 有内容 | LOW-001: K8s labs 缺此字段 |
| `ai_tutor_context` | ❌ 字段缺失 | ✅ 有内容 | K8s labs 缺此字段 |
| `troubleshoot` per step | ❌ 字段缺失 | ✅ 有内容（4步均有） | MEDIUM-002: K8s labs 缺此字段 |
| `article_url` | ❌ 所有 6 个均无 | ❌ 所有 6 个均无 | **P0 Gap** |
| `source_article_id` | ✅ 有内部 ID | ✅ 有内部 ID | 仅内部使用 |
| `verify` specs | ✅ 完整（每步 1 条） | N/A（用 linux_verify） | — |
| `linux_verify` specs | N/A | ✅ 完整（步骤有 0-3 条） | — |

---

## Reuse Guidelines for New Labs

### 创建新 K8s lab 时

1. 复用 K8s step schema（why/do/commands/observe/explain/verify）
2. `explain` 为字符串
3. `verify` 数组：每步至少 1 条，type 从已有类型中选
4. 不需要 `linux_verify`、`troubleshoot`（K8s lab 当前无此字段，但建议加入）
5. `experiment_background`、`completion_summary`、`ai_tutor_context` 应填写（当前 K8s lab 缺失此字段是内容遗留问题）

### 创建新 Linux lab 时

1. 复用 Linux step schema（比 K8s 多 `linux_verify` + `troubleshoot`）
2. `explain` 为对象（含 concept/observation/confidence/admin_verified/published_to_student）
3. `linux_verify` 数组：每步至少 1 条（最后一步可为空列表若仅是 cleanup 说明）
4. `troubleshoot` 每步必填（字符串，描述常见失败原因和解决方法）
5. `experiment_background` 必填（Linux lab 有此字段）
6. `completion_summary` 必填

### 通用约束

- `schema_version: "1.0"` 每个 step 和 verify 都需要
- `rehearsal_required: true` 发布前必须通过内部排练
- `rehearsal_completed: true` 发布门控检查此字段
- 步骤数量：建议 2-5 步（当前范围 1-4 步）
- 时长：建议 10-30 分钟

---

## CTA Format（当前标准）

已定义的 CTA deep link 格式：

```
/labgen-lab.html?labId=<lab_uuid>
```

示例：
```
https://lab.cloudnetops.tech/labgen-lab.html?labId=6c439064-4cad-4229-addb-36927128d565
```

**现状**：格式已定义、已验证（G-47、G-32），但无标准 CTA 文案模板，无 admin 工具生成此链接。详见 [PHASE1_GAP_PRIORITIZATION_v0.1.md](PHASE1_GAP_PRIORITIZATION_v0.1.md)。
