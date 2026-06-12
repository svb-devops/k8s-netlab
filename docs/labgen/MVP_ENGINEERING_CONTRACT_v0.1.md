# LabGen MVP Engineering Contract v0.1

> 本文件是 LabGen 功能的工程约定文件（Engineering Contract）。
> 所有模块的接口设计、数据结构、状态机、阻断规则均以本文件为准。
> 实现不得与本文件矛盾，发现矛盾时修改实现，不修改本文件（除非通过正式 Contract 修订）。

---

## 1. Scope and Non-goals

### Scope（MVP）

- **Lab Draft Generator**：从技术文章生成结构化实验草稿（两阶段 LLM 流水线）
- **Static Validator**：对草稿做结构、安全、镜像、权限的静态检查，输出统一的 `ValidatorResult`
- **Admin Review Workflow**：管理员查看草稿、修改字段、审核风险、记录 diff、确认发布
- **Image Resolver**：将 LLM 表达的镜像意图映射到内网 registry 具体 tag，并在 publish 和 lab start 时验证存在性
- **Lab Session Lifecycle**：学生从开始实验到 cleanup 完成的完整状态机
- **Verification System**：FastAPI 通过 verifier kubeconfig 调用 K3s API 验证实验步骤
- **Verifier Credential Lifecycle**：verifier kubeconfig 的创建、存储、权限绑定、轮换、回收

### Non-goals（MVP 明确排除，禁止实现）

| 排除项 | 说明 |
|--------|------|
| URL crawling | 文章必须由管理员粘贴/输入，不爬取外部 URL |
| Shared namespace runtime | MVP 只支持 Dedicated VM，禁止多学生共享 K3s |
| VM agent | 平台侧验证通过 FastAPI 直连 K3s API，不在 VM 内部署 agent |
| Free-form shell verify | 所有验证必须用结构化 Verify Template，禁止任意 shell 命令 |
| Helm generation | LabGen 不主动生成 Helm-based 实验；文章含 Helm → high-risk 草稿，管理员手写，dedicated VM only |
| Helm template scanning | Helm chart 渲染和依赖解析是 Phase 2 |
| secret_key_exists / secret_value_equals | MVP verifier 不读 Secret data，仅 list secret 名称 |
| Automatic publish | 所有草稿必须经管理员审核后手动发布 |
| External registry images | 所有镜像必须解析到内网 registry（<registry-host>:5000），禁止 admin_approved_external |
| Admin force cleanup | Phase 2；MVP 由学生动作或 session 超时触发 cleanup |

---

## 2. Runtime Architecture

```
Directus 文章
  ↓ 管理员触发
LabGen API (FastAPI)
  ↓
Stage 1: ArticleAnalyzer      → 可操作性评分 + 命令/资源/前置条件提取
Stage 2: LabDraftGenerator    → steps(why/do/observe/explain/verify) + cleanup + runtime_requirements
  ↓
StaticValidator               → 输出 List[ValidatorResult]，含 blocking_level
  ↓
Admin Review UI               → 字段可编辑，explain 标红，镜像解析表，记录 diff
  ↓
Publish (blocking_level=publish_blocking 全部 passed 才可发布)
  ↓
Lab Session (Dedicated VM K3s，namespace per lab/session)
  ↓
Verification (FastAPI → vm_ip:6443，使用 verifier kubeconfig，namespace RoleBinding)
```

**三类凭证，严格分离：**

| 凭证 | 权限 | 用途 |
|------|------|------|
| student kubeconfig | lab namespace 受限读写 | 学生终端 |
| verifier kubeconfig | lab namespace list-only（见 §14） | FastAPI 自动验证 |
| admin kubeconfig | cluster-admin | 平台运维/调试/紧急修复，禁止用于常规 verify |

---

## 3. Schema Versioning and Migration Rules

> 本节故意提前，所有 Schema 定义均依赖本节规则。

所有 JSON 结构必须包含 `"schema_version": "1.0"` 字段。

**升级规则：**

| 变更类型 | 版本变化 | 处理方式 |
|---------|---------|---------|
| 新增可选字段 | 1.0 → 1.1（Minor） | 向前兼容，旧草稿可自动读取（缺失字段用默认值） |
| 新增必填字段 / 删除字段 / 语义变更 | 1.0 → 2.0（Major） | 需迁移脚本，旧草稿阻断发布直到迁移完成 |

**必须有 schema_version 的对象：**
- `LabDraft`
- `Step`
- `VerifyTemplate`
- `RuntimeRequirements`
- `ImageResolutionResult`
- `VerifierCredentialMetadata`
- `LabSessionState`
- `AdminReviewDiff`
- `ValidatorResult`

---

## 4. Lab Draft JSON Schema

```json
{
  "schema_version": "1.0",
  "lab_id": "<uuid>",
  "source_article_id": "<directus_article_id>",
  "title": "<string>",
  "description": "<string>",
  "estimated_duration_minutes": "<integer>",
  "prerequisites": ["<string>"],
  "runtime_requirements": "<RuntimeRequirements>",
  "steps": ["<Step>"],
  "cleanup": "<CleanupSpec>",
  "image_resolution": ["<ImageResolutionResult>"],
  "pollution_level": "namespace_only | cluster_scoped | node_level | unknown",
  "shared_namespace_candidate": "<boolean, 系统推导>",
  "shared_namespace_candidate_reason": "<string, 推导依据>",
  "publish_status": "draft | review_required | publish_blocked | published",
  "validator_results": ["<ValidatorResult>"],
  "created_at": "<ISO8601>",
  "updated_at": "<ISO8601>"
}
```

**字段约束：**
- `lab_id`：UUID v4，生成时赋值，不可更改
- `pollution_level`：由 StaticValidator 推导，LLM 不得输出此字段
- `shared_namespace_candidate`：由 StaticValidator 推导，LLM 不得输出此字段（见 §7）
- `publish_status`：系统维护，人工不可直接设置为 `published`，必须通过 publish API

---

## 5. Step Schema（why / do / observe / explain / verify）

```json
{
  "schema_version": "1.0",
  "step_id": "<string, 唯一>",
  "order": "<integer>",
  "why": "<string, 本步做什么和为什么>",
  "do": "<string, 操作描述>",
  "commands": ["<string, 每条命令>"],
  "observe": "<string, 期望看到的现象>",
  "explain": {
    "concept": "<string, 解释概念>",
    "observation": "<string, 解释现象背后原因>",
    "confidence": "unverified | admin_verified",
    "admin_verified": false,
    "published_to_student": false
  },
  "verify": ["<VerifyTemplate>"]
}
```

**explain 字段规则：**
- LLM 生成后默认 `confidence: "unverified"`, `admin_verified: false`, `published_to_student: false`
- Admin Review UI 必须对 `explain.concept` 和 `explain.observation` 标红警示，要求管理员逐项确认
- `published_to_student: true` 只能由管理员手动设置为 `true`，设置后才显示给学生
- 若 `published_to_student: true` 但 `admin_verified: false` → `ValidatorResult` 输出 `publish_blocking`

**字段风险标注（Admin UI 展示用）：**

| 字段 | 风险级别 | 说明 |
|------|---------|------|
| why | medium | 目标表述可能不准确 |
| do | low | 操作性描述，通常正确 |
| observe | medium | 现象描述可能平台相关 |
| explain.concept | high | 概念解释易出错，必须管理员核实 |
| explain.observation | high | 现象归因易过度解释，必须管理员核实 |

---

## 6. Verify Template Schema

```json
{
  "schema_version": "1.0",
  "verify_id": "<string>",
  "type": "pod_running | pod_ready | service_exists | deployment_ready | configmap_exists | secret_exists | namespace_exists | node_ready | pvc_bound | job_completed",
  "namespace": "{{lab_namespace}}",
  "name": "<string>",
  "label_selector": "<string, 可选>",
  "cluster_scope": false,
  "supported_runtimes": ["dedicated_vm"],
  "blocking_level_on_fail": "publish_blocking | review_required",
  "manual_review_required": false,
  "notes": "<string, 可选，管理员注释>"
}
```

**类型约束：**
- `namespace` 必须使用 `{{lab_namespace}}` 变量，禁止硬编码 `default`、`demo`、`kube-system` 等
- cluster-scoped 验证（如 `node_ready`）必须设置 `cluster_scope: true` 且 `manual_review_required: true`
- MVP 支持的 type 集合固定，不在列表中的 → `manual_review_required: true`，ValidatorResult 输出 `review_required`

**MVP 禁止的 verify type：**
- 任何 shell 命令执行
- `secret_key_exists`（需要读 Secret data）
- `secret_value_equals`

---

## 7. Image Resolver Schema

**设计原则：LLM 只表达意图（"需要 nginx 类型的镜像"），系统决定具体 tag。**

### ImageResolutionResult

```json
{
  "schema_version": "1.0",
  "image_intent": "nginx",
  "requested_image": "nginx:alpine",
  "resolved_image": "<registry-host>:5000/nginx:1.25-alpine",
  "image_status": "resolved | unresolved | blocked",
  "existence_checked_at": "<ISO8601 | null>",
  "existence_check_passed": "<boolean | null>",
  "recheck_after_hours": 24
}
```

**image_status 定义：**
- `resolved`：成功映射到内网 registry 且 existence check 通过
- `unresolved`：whitelist 中不存在，需管理员干预
- `blocked`：含 `:latest`、未知 registry、无 tag 等，直接阻断

### Image Whitelist 结构（`config/image_whitelist.json`）

```json
{
  "nginx": {
    "default": "<registry-host>:5000/nginx:1.25-alpine",
    "aliases": ["nginx", "web-server"]
  },
  "busybox": {
    "default": "<registry-host>:5000/busybox:1.36",
    "aliases": ["shell", "debug", "toolbox"]
  },
  "alpine": {
    "default": "<registry-host>:5000/alpine:3.19",
    "aliases": ["alpine"]
  },
  "curl": {
    "default": "<registry-host>:5000/curlimages/curl:8.5.0",
    "aliases": ["http-client", "curl"]
  }
}
```

### Registry Existence Check

- **Publish 时**：所有 image 的 `existence_check_passed` 必须为 `true`，否则阻断发布
- **Lab Start 时**：若距上次 existence check 超过 `recheck_after_hours`，重新检查。失败时不进入实验，显示"该实验依赖镜像当前不可用，已通知管理员"，不让学生进终端遇到 ImagePullBackOff
- **Check 方式**：`GET https://<registry-host>:5000/v2/{name}/manifests/{tag}`，HTTP 200 = 存在

### 静态检查阻断规则

| 条件 | 处理 |
|------|------|
| `image:latest` | `blocked`，publish_blocking |
| 含 `docker.io/`, `ghcr.io/`, `quay.io/` 等外部 registry | `blocked`，publish_blocking |
| 无 tag | `blocked`，publish_blocking |
| initContainer 镜像未解析 | `unresolved`，publish_blocking |
| whitelist 未命中 | `unresolved`，publish_blocking |

### 静态扫描范围（StaticValidator 必须覆盖）

所有 YAML 中的 image 字段，包括：
`spec.containers[].image`, `spec.initContainers[].image`, `spec.ephemeralContainers[].image`，
适用于：Pod, Deployment, StatefulSet, DaemonSet, Job, CronJob

---

## 8. Runtime Requirements Schema

```json
{
  "schema_version": "1.0",
  "runtime": "dedicated_vm",
  "namespace_template": "lab-{{lab_id}}-{{session_id}}",
  "cluster_scoped_resources": [
    {
      "kind": "ClusterRole",
      "name": "demo-reader",
      "api_group": "rbac.authorization.k8s.io",
      "cleanup": "delete"
    }
  ],
  "pollution_level": "namespace_only | cluster_scoped | node_level | unknown",
  "shared_namespace_candidate": false,
  "shared_namespace_candidate_reason": "<string>"
}
```

### pollution_level 定义

| 级别 | 含义 | 下一个实验前处理 |
|------|------|----------------|
| `namespace_only` | 只有 namespace 内资源 | 删除 namespace 即可 |
| `cluster_scoped` | 有 cluster-scoped 资源 | 执行显式 cleanup + 验证 |
| `node_level` | 有节点级别资源（hostPath 等） | 实验结束后回收 VM |
| `unknown` | 无法静态确定 | 禁止发布 |

### shared_namespace_candidate 推导规则（系统自动，LLM 不参与）

满足**全部**以下条件才为 `true`：
1. 所有 verify 模板 `cluster_scope: false`
2. 无 ClusterRole / CRD / StorageClass / Node 类资源
3. 无 hostPath / hostNetwork / hostPID
4. 无 NodePort Service
5. 无 Ingress（MVP 阶段，Ingress 支持 Phase 2）
6. 无 PVC（MVP 阶段，PVC 支持 Phase 2）
7. 无 Helm 命令
8. 无 CRD / Operator
9. 所有镜像 image_status = `resolved`

否则为 `false`，并在 `shared_namespace_candidate_reason` 中记录首个不满足条件。

---

## 9. Static Validator and Blocking Levels

所有 validator 检查的输出格式：

```json
{
  "schema_version": "1.0",
  "check_id": "<string, 唯一标识如 'image.registry.exists'>",
  "status": "passed | failed | warning",
  "blocking_level": "draft_warning | review_required | publish_blocking | runtime_blocking",
  "field_path": "<string, 指向具体字段如 'steps[0].verify[1].namespace'>",
  "message": "<string>"
}
```

### blocking_level 定义

| 级别 | 含义 |
|------|------|
| `draft_warning` | 可保存草稿，Admin UI 显示提示 |
| `review_required` | 必须管理员手动确认后才可进入 publish 流程 |
| `publish_blocking` | 不允许发布，必须修复 |
| `runtime_blocking` | 已发布但当前无法启动（如镜像不可用）；显示错误给学生，通知管理员 |

---

## 10. Publish Blocking Rules

发布前 StaticValidator 的以下检查全部为 `passed` 才允许发布：

| check_id | 条件 | blocking_level |
|----------|------|---------------|
| `image.no_latest_tag` | 所有镜像无 `:latest` | publish_blocking |
| `image.no_unknown_registry` | 无 docker.io/ghcr.io/quay.io 等 | publish_blocking |
| `image.all_resolved` | 所有镜像 image_status = resolved | publish_blocking |
| `image.all_exist_in_registry` | 所有 resolved 镜像 registry existence check 通过 | publish_blocking |
| `explain.verified_if_published` | explain.published_to_student=true 必须 admin_verified=true | publish_blocking |
| `namespace.no_hardcoded` | 无硬编码 default/demo/kube-system namespace | publish_blocking |
| `pollution.known` | pollution_level != unknown | publish_blocking |
| `verify.no_shell_commands` | 无 free-form shell verify | publish_blocking |
| `verify.no_secret_value` | 无 secret_value_equals / secret_key_exists | publish_blocking |
| `cleanup.declared` | cleanup spec 存在且非空 | publish_blocking |
| `cluster_scoped.cleanup_declared` | cluster_scoped_resources 每项都有 cleanup 字段 | publish_blocking |
| `helm.no_generation` | LLM 生成内容无 `helm install/upgrade` | review_required |
| `service.nodeport` | 含 NodePort Service → shared_namespace_candidate=false | review_required |
| `operator.crd` | 含 CRD/Operator → requires_dedicated_vm=true | review_required |

---

## 11. Lab Session State Machine

### 状态转换（per-lab）

```
LAB_CREATED
  → LAB_STARTING
  → VM_PRECHECK_RUNNING
  → (失败) → LAB_START_FAILED [终态]
  → IMAGE_CHECK_RUNNING
  → (失败) → LAB_START_FAILED [终态]
  → NAMESPACE_CREATING
  → NAMESPACE_READY
  → LAB_ACTIVE
  → LAB_COMPLETED | LAB_ABORTED | LAB_TIMEOUT
  → CLEANUP_REQUESTED
  → NAMESPACE_TERMINATING_WAIT
  → (超时 > 5min) → [发出 LAB_SESSION_VM_TAINTED 事件] → LAB_CLEANUP_FAILED [终态]
  → CLEANUP_VERIFICATION_RUNNING
  → (失败) → [发出 LAB_SESSION_VM_TAINTED 事件] → LAB_CLEANUP_FAILED [终态]
  → CLEANUP_VERIFIED
  → LAB_CLOSED [终态]
```

### VM_PRECHECK_RUNNING 通过条件（全部满足）

1. VM 当前状态不为 TAINTED
2. 该 VM 无其他 active lab session（状态 ∉ {LAB_CLOSED, LAB_START_FAILED, LAB_CLEANUP_FAILED}）
3. 目标 namespace（`lab-{{lab_id}}-{{session_id}}`）不存在
4. 无前一个 namespace 处于 Terminating 状态超过 5 分钟
5. 前一个 lab session 状态为 LAB_CLOSED，或无前一个 session
6. 若前一个 lab 声明了 `cluster_scoped_resources`，其 cleanup_verified = true

任意条件不满足 → 进入 `LAB_START_FAILED`，向用户显示具体原因。

### connection_state 与 lab_session_state 分离

WebSocket 断开**不触发** cleanup。只影响 `connection_state`：

```
connection_state: connected | disconnected | reconnecting
```

`lab_session_state` 独立维护，不受 WebSocket 状态影响。

---

## 12. Cleanup Trigger Rules

| 触发条件 | MVP 支持 | 触发方 |
|---------|---------|--------|
| 学生点击"完成实验" | 是 | 前端 → `POST /lab-sessions/{id}/complete` |
| 学生点击"放弃实验" | 是 | 前端 → `POST /lab-sessions/{id}/abort` |
| VM session 超时（vm_tracker 过期） | 是 | vm_tracker 过期回调 → `LAB_TIMEOUT` |
| WebSocket 断开 | 否 | 仅更新 connection_state |
| 管理员强制回收 | Phase 2 | - |

---

## 13. VM Tracker / Lab Session Event Boundary

**原则：Lab Session 不直接管理 VM 生命周期，只发事件。VM Tracker 决定 VM 状态。**

### Lab Session → VM Tracker 事件

```json
{ "event": "LAB_SESSION_STARTED",          "vm_id": "...", "lab_session_id": "..." }
{ "event": "LAB_SESSION_CLEANUP_VERIFIED",  "vm_id": "...", "lab_session_id": "..." }
{ "event": "LAB_SESSION_VM_TAINTED",        "vm_id": "...", "lab_session_id": "...", "reason": "namespace_deletion_timeout | cluster_scoped_cleanup_failed" }
```

### VM Tracker → Lab Session 查询接口

```python
is_vm_available(vm_id: str) -> bool
is_vm_tainted(vm_id: str) -> bool
mark_vm_tainted(vm_id: str, reason: str) -> None
mark_vm_ready(vm_id: str) -> None
```

---

## 14. Verifier Credential Lifecycle

### Credential Metadata Schema

```json
{
  "schema_version": "1.0",
  "vm_id": "<string>",
  "created_at": "<ISO8601>",
  "expires_at": "<ISO8601>",
  "k3s_endpoint": "https://<vm_ip>:6443",
  "credential_type": "verifier",
  "permission_profile": "namespace_readonly_v1",
  "credential_generation": 1,
  "revoked_at": null
}
```

### 存储规范

- **路径**：`creds/vm_creds/{vm_id}_verifier.yaml`（独立于 `data/`）
- **目录权限**：`chmod 700 creds/vm_creds/`
- **文件权限**：`chmod 600 creds/vm_creds/*`
- **备份**：从 `scripts/backup-data.sh` 中明确排除，不得进入常规备份
- **日志**：任何异常打印中禁止输出 kubeconfig 内容
- **回收**：vm_tracker 回收 VM 时必须同步删除对应凭证文件；删除失败记录 `credential_cleanup_failed` 并告警

### VM 初始化函数拆分（幂等）

当前 `reset_k3s_via_agent` 需拆分并保持幂等：

```python
reset_k3s_via_agent(vm)      # K3s reset，hostname，etcd 清理
ensure_registry_config(vm)   # registry mirror 配置
ensure_verifier_identity(vm) # 创建 lab-verifier ServiceAccount + ClusterRole（kubectl apply -f -）
export_verifier_kubeconfig(vm) # 生成 verifier token，写入 creds/
```

所有函数必须可重复调用（幂等），`kubectl apply` 而非 `kubectl create`。

### Verifier Kubeconfig Smoke Test

生成后必须验证（FastAPI 内嵌检查）：

| 测试 | 预期结果 |
|------|---------|
| list pods in lab namespace | 允许 |
| delete pod in lab namespace | 拒绝（403） |
| get secret value in lab namespace | 拒绝（403） |
| list pods in kube-system | 拒绝（403） |
| get nodes | 拒绝（403） |

任意测试未通过 → VM 不进入 READY 状态，记录错误，告警。

---

## 15. Verifier Permission Profiles

### namespace_readonly_v1

**绑定方式**：每个 lab session 开始时，为该 session 的 namespace 创建 `RoleBinding`（不使用 ClusterRoleBinding）。

```yaml
# ClusterRole（在 VM 初始化时创建，MVP 只有这一个）
rules:
  - apiGroups: [""]
    resources: ["pods", "services", "endpoints", "configmaps", "events"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["list"]          # 只给 list，不给 get（无法读取 Secret.data）
  - apiGroups: ["apps"]
    resources: ["deployments", "replicasets", "statefulsets", "daemonsets"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["batch"]
    resources: ["jobs", "cronjobs"]
    verbs: ["get", "list", "watch"]
```

**不允许**：
- `secrets.get`（会暴露 Secret.data）
- 任何 `create/update/delete/patch`
- cluster-scoped 资源的读取（除非 verify 模板显式声明 cluster_scope: true 且 manual_review_required: true）

**Permission Profile Metadata（写入 credential metadata）：**

```json
{
  "permission_profile": "namespace_readonly_v1",
  "secret_access": "list_only",
  "secret_get_allowed": false,
  "secret_value_read_allowed": false
}
```

---

## 16. Admin Review Diff Schema

```json
{
  "schema_version": "1.0",
  "lab_draft_id": "<string>",
  "admin_user": "<string>",
  "reviewed_at": "<ISO8601>",
  "review_duration_seconds": "<integer>",
  "changes": [
    {
      "field_path": "steps[0].explain.concept",
      "change_type": "edit | approve | reject | confirm",
      "original_value": "<string>",
      "edited_value": "<string | null>",
      "note": "<string, 可选>"
    }
  ]
}
```

Diff 记录用途：
1. 审计（管理员改了什么）
2. 训练数据（`explain.concept` 的修改率 = LLM 能力评估指标）
3. 未来 fine-tuning 数据集

---

## 17. API Endpoints

### 公开 API（需认证）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/labgen/drafts` | 从文章内容生成草稿 |
| GET | `/api/labgen/drafts/{id}` | 获取草稿 |
| PATCH | `/api/labgen/drafts/{id}` | 管理员修改草稿字段 |
| POST | `/api/labgen/drafts/{id}/validate` | 触发静态验证，返回 `List[ValidatorResult]` |
| POST | `/api/labgen/drafts/{id}/publish` | 发布（所有 publish_blocking 检查通过才成功） |
| GET | `/api/lab-sessions/{id}` | 获取 lab session 当前状态 |
| POST | `/api/lab-sessions` | 学生开始实验（创建 lab session） |
| POST | `/api/lab-sessions/{id}/complete` | 学生完成实验 |
| POST | `/api/lab-sessions/{id}/abort` | 学生放弃实验 |
| POST | `/api/images/resolve` | 解析镜像意图（支持批量传入多个 image_intent） |
| POST | `/api/images/check-existence` | 检查镜像在内网 registry 是否存在 |

### 内部 API（不对学生暴露）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/internal/verifier/check` | 执行单个 VerifyTemplate（Lab Session 状态机调用） |
| POST | `/internal/lab-sessions/{id}/cleanup` | 触发 cleanup（vm_tracker 超时回调用） |

---

## 18. Cleanup Spec Schema

```json
{
  "namespace_cleanup": {
    "type": "delete_namespace",
    "namespace": "{{lab_namespace}}"
  },
  "cluster_scoped_resources": [
    {
      "kind": "ClusterRole",
      "name": "demo-reader",
      "api_group": "rbac.authorization.k8s.io",
      "cleanup": "delete"
    }
  ],
  "cleanup_verified": false
}
```

**规则：**
- `namespace_cleanup` 是必填字段，不可为空；类型为结构化对象（非 shell 字符串），平台调用 Kubernetes API 执行，不通过 shell 执行
- 若 `cluster_scoped_resources` 非空，每项必须有 `cleanup` 字段
- `cleanup_verified` 在 CLEANUP_VERIFICATION_RUNNING 通过后设为 true

---

## 推荐实现顺序

第一个实现模块：**StaticValidator + Schema Models**（不从 LLM 生成器开始）

原因：StaticValidator 是整个系统的"前提执行器"，可纯逻辑测试，不依赖 LLM 或 K3s。实现后可立即验证 Contract 是否自洽。

```
1. Pydantic models（LabDraft, Step, VerifyTemplate, ImageResolutionResult,
                   RuntimeRequirements, ValidatorResult）
2. StaticValidator 基础框架
3. Image static scan（禁 latest、未知 registry、无 tag、未解析镜像）
4. Namespace hardcode check
5. Verify template check（禁 shell verify、禁 secret key/value）
6. Publish blocking aggregation
7. shared_namespace_candidate 自动推导
8. pollution_level 自动推导
```

然后实现 Image Resolver + registry existence check。

---

## 合同修订记录

| 版本 | 日期 | 变更摘要 |
|------|------|---------|
| v0.1 | 2026-06-07 | 初稿，基于五轮架构讨论达成的共识 |
| v0.1.1 | 2026-06-07 | GET /images/resolve → POST（支持批量）；namespace_cleanup 改为结构化对象，平台调用 K8s API |
