# Second Wave #1 Minimal Publish — 生产结果报告 v0.1

## 元信息

- Lab: `ce793f9b-e416-44e2-9a32-c79b6488cfa2`（ConfigMap 修改后不生效排查实验）
- Directus article: id=7，slug `configmap-not-effective-rollout-restart`
- 状态：`overall_status = CONFIGMAP_PUBLISHED_AND_SERIES_VERIFIER_PATH_VALIDATED`

## 发布前确认

| 项 | 状态 |
|---|---|
| rehearsal_completed | true |
| Owner dogfood | 已完成（8/8 步骤，`cleanup_verified=true`） |
| cleanup_verified | true |
| article final draft | 存在（`docs/labgen/articles/CONFIGMAP_NOT_EFFECTIVE_OFFICIAL_ARTICLE_FINAL_DRAFT_v1.0.md`） |
| Directus/health/git | 正常 |
| 全局 verifier vm_id pin 修复 | 已部署（commit `7d4f8f4`） |

发布前 baseline 记录：`LABGEN_ENABLED_LAB_IDS`/`LABGEN_AUTO_VM_PROVISION_LAB_IDS` 均为 First Wave 三个 lab_id；`labgen_invites.json` 不存在；ConfigMap draft `cta_enabled=false`、`article_url=null`。

## 发布内容

- Directus 创建正式 article（`status=published`，`public_publish_version` CTA 文案，无内部 metadata/lab_id/credentials/发布 checklist 测试记录，`https://lab.cloudnetops.tech/api/articles/configmap-not-effective-rollout-restart` 与 `article.html?slug=...` 均验证 200），加入《Kubernetes 高频故障排查实战系列》互链（新文章链向另外三篇，未反向修改另外三篇已发布文章的正文——超出本次 minimal publish 范围）
- `lab_id` 同步加入 `LABGEN_ENABLED_LAB_IDS` 与 `LABGEN_AUTO_VM_PROVISION_LAB_IDS`
- LabDraft PATCH：`cta_enabled=true`、`article_url` 指向新文章、`article_channel=official_site`
- 未启用 invite 限制——访问模型与另外三个已发布 lab 完全一致
- 未启动 DNS/Pod Pending 后续主题，未做 Growth/外部文章

## 发布后真实端到端验证

用全新注册账号 `cm-e2e-fresh-01`（非 admin、注册时无预分配 VM）走完整公开路径：

```
文章(200) → CTA(has_cta=true) → Start Lab → 自动 provisioning(ready)
→ LAB_ACTIVE(vm_id=500，自动分配) → 8/8 步骤全部通过 → complete
→ LAB_CLOSED → cleanup_verified=true
```

session_id: `a951b647-81cb-4305-9d24-393507557894`

### 核心语义人工/机器双重确认

verifier 走的是既有机器判定（`configmap_value_equals`/`deployment_restart_not_triggered`/`deployment_restart_triggered`/`deployment_ready`，8 步全 PASS）。额外用平台管理员权限（`kubectl exec`，非学员/verifier 路径，仅用于本次验证）直接读取容器进程内的真实环境变量值，交叉确认：

| 阶段 | Pod | 进程内 `APP_MODE` |
|---|---|---|
| 初始（rollout restart 前） | `demo-86549bf9fc-vw9jl` | `old` |
| ConfigMap 已 patch 为 new，尚未 restart | `demo-86549bf9fc-vw9jl`（同一个 Pod） | `old` |
| rollout restart 后 | `demo-8675c7c955-f87fs`（新 Pod） | `new` |

三个核心教学语义在真实新用户会话、真实 K3s 集群上完整成立，不是理论推断。

## 系列关键 verifier 回归（同一账号依次验证，不要求走完整个 lab）

| Lab | session_id | 代表性 verifier | 结果 | cleanup_verified |
|---|---|---|---|---|
| CrashLoopBackOff | `ae333c6b-2fee-48fc-860b-ec160f781cb0` | `deployment_unavailable` | PASS | true |
| Service No Endpoints | `b45bb3f4-7c0c-4641-8923-4a68d4a8e43a` | `service_has_endpoints`（修复后） | PASS | true |
| ImagePullBackOff | `ca255350-85d3-4da3-a08a-2e7a42e43cb7` | `deployment_unavailable` | PASS | true |

三个 session 均：真实执行代表性 kubectl 命令 → verify 明确 PASS（无 500、无 credential_missing）→ abort → `LAB_CLOSED` → `cleanup_verified=true`。确认上一轮 `LABGEN_K8S_VERIFIER_VM_ID` pin 修复对整个系列都生效，不是只对 ConfigMap 单个 lab 生效。

## 访问范围回归

- 四个系列 lab（CrashLoopBackOff/Service No Endpoints/ImagePullBackOff/ConfigMap）`is_startable=true`
- 非系列 lab（Linux draft 等）访问策略未变
- ConfigMap article 公开可访问，CTA 指向正确 lab
- First Wave 三篇文章状态未变
- 未发现任何内部信息泄漏（VMID/Proxmox/credentials path）

## 资源与健康检查

- `active_session_count=0`，`tainted_vm_count=0`，无残留 provisioning job
- `cm-e2e-fresh-01` 测试期间使用的 VM 500 已通过标准 API 删除，`VMTracker.get_user_vms('cm-e2e-fresh-01')` 确认为空
- 三次系列回归 + 一次 ConfigMap 完整验证共产生的 4 个 namespace 全部确认已回收（`kubectl get ns` NotFound）
- 近 30 分钟无新增错误日志，`/api/health` 全程 `healthy`
- git 状态干净

## 测试

全量测试跑于上一轮 verifier 修复提交（`7d4f8f4`），本次未改动任何代码，仅 Directus 内容 + `.env` 配置 + LabDraft 元数据，不触发新的单元测试需求。

## 回滚

未触发。全程无 BLOCKER/HIGH。

## 遗留

- Second Wave 后续两个主题（DNS 服务发现失败、Pod Pending）按决策本轮不启动
- 另外三篇已发布文章未反向添加指向 ConfigMap 文章的链接（本次 minimal publish 范围内未做，如需要可作为后续小改动）
