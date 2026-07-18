# Second Wave #2 Minimal Publish — DNS Service Discovery 生产结果报告 v0.1

## 元信息

- Lab: `39b87766-a7eb-460d-a8d3-ac5a31319d4a`（DNS 服务发现失败排查实验）
- Directus article: id=8，slug `dns-service-discovery-namespace-fqdn`
- 状态：`overall_status = DNS_PUBLISHED_AND_FIVE_ARTICLE_SERIES_READY`

## 发布前确认

| 项 | 状态 |
|---|---|
| 终端换行符 bug 修复 | 已 commit（`5359364`）、push、部署（静态文件免重启，`curl` 确认生产文件与已测试提交逐字节一致） |
| git | clean |
| health | healthy |
| DNS shared target（`labgen-dns-target`） | namespace Active，Deployment 1/1 ready，Service 存在，Endpoints 非空 |
| DNS lab rehearsal/dogfood/cleanup 记录 | 完整（两轮 rehearsal + 一次 Owner 真实 dogfood，`LAB_CLOSED`+`cleanup_verified=true`） |
| article final draft | 存在（`docs/labgen/articles/DNS_SERVICE_DISCOVERY_OFFICIAL_ARTICLE_FINAL_DRAFT_v1.0.md`） |

发布前 baseline 记录：`LABGEN_ENABLED_LAB_IDS`/`LABGEN_AUTO_VM_PROVISION_LAB_IDS` 均为前四个已发布 lab_id；DNS draft 此前 `publish_status=published`（Owner dogfood 时已补齐）、`cta_enabled=false`、`article_url=null`。

## 发布内容

- Directus 创建正式 article（`status=published`，正文取自 `ready_to_publish_draft` 去除内部 `internal_preview_version` 尾注后的 `public_publish_version`，无 lab_id/VMID/Proxmox/测试记录/内部 checklist；`https://lab.cloudnetops.tech/api/articles/dns-service-discovery-namespace-fqdn` 与 `article.html?slug=...` 均 200）
- `lab_id` 同步加入 `LABGEN_ENABLED_LAB_IDS` 与 `LABGEN_AUTO_VM_PROVISION_LAB_IDS`
- LabDraft PATCH：`cta_enabled=true`、`article_url` 指向新文章、`article_channel=official_site`
- 未启用 invite 限制——访问模型与另外四个已发布 lab 完全一致
- 未启动 Pod Pending 后续主题，未做 Growth/外部文章，未做数据迁移

## 发布后真实端到端验证

用全新注册账号 `dns-e2e-fresh-01`（非 admin、注册时无预分配 VM）走完整公开路径：

```
文章(200) → CTA(has_cta=true) → Start Lab → 自动 provisioning(ready)
→ LAB_ACTIVE(vm_id=500，自动分配) → 4/4 步骤全部通过 → complete
→ LAB_CLOSED → cleanup_verified=true
```

session_id: `52d8bb71-81fe-45f9-85af-6f32ea22213c`

### 终端换行符修复的发布后验证

- 生产环境实际提供的 `https://lab.cloudnetops.tech/js/labgen-kubectl-terminal.js` 与已测试、已提交的源码逐字节一致（`diff` 确认）
- 该账号依次执行 3 条真实 kubectl 命令（创建诊断 Deployment、`kubectl logs`、`kubectl delete deployment`），全部通过 WebSocket 终端成功执行并推进步骤（`kubectl logs -l app=dns-check` 是第二条命令，正是此前 Owner 报告"闪一下无输出"的同一类操作，此次顺畅完成）
- 核心教学语义机器验证：`kubectl logs` 输出确认 `SHORT_NAME_FAILED_AS_EXPECTED` 与 `SERVICE_FQDN_RESOLVED` 两个标记，`pod_log_contains` verifier 均 PASS

## 系列文章导航统一

五篇已发布文章互相补齐了最小系列导航：

| # | slug | 状态 | 本次改动 |
|---|---|---|---|
| 1 | crashloopbackoff-describe-logs | published | 系列文章段追加指向 DNS 文章的链接 |
| 2 | service-no-endpoints-selector-labels | published | 同上 |
| 3 | imagepullbackoff-events-diagnosis | published | 同上 |
| 4 | configmap-not-effective-rollout-restart | published | 同上 |
| 5 | dns-service-discovery-namespace-fqdn | published（新） | 正文已包含指向前四篇的链接 |

全部 5 个文章 slug 实测 `GET /api/articles/{slug}` 200，无死链；未创建新的独立 series page，导航完全内嵌在各篇文章正文的"系列文章"段落里。

## 访问范围回归

- 五个系列 lab（CrashLoopBackOff/Service No Endpoints/ImagePullBackOff/ConfigMap/DNS）`is_startable=true`
- 非系列 lab（Linux draft 等）访问策略未变
- DNS article 公开可访问，CTA 指向正确 lab
- 其余四篇文章状态未变（均 published）
- 未发现任何内部信息泄漏（VMID/Proxmox/credentials path/checklist）；文章正文中出现的 `labgen-dns-target` 是有意的教学内容（FQDN 示例本身），非敏感信息泄漏

## 资源与健康检查

- `active_session_count=0`，`tainted_vm_count=0`，无残留 provisioning job
- `dns-e2e-fresh-01` 测试期间使用的 VM 500 已通过标准 API 删除，`VMTracker` 确认为空
- 本次验证产生的 namespace 已确认回收（`kubectl get ns` NotFound）
- 近期无新增错误日志，`/api/health` 全程 `healthy`
- git 状态干净

## 测试

全量测试跑于终端修复提交（`5359364`），本次未改动任何代码，仅 Directus 内容 + `.env` 配置 + LabDraft 元数据，不触发新的单元测试需求。

## 回滚

未触发。全程无 BLOCKER/HIGH。

## 遗留

- Second Wave 后续主题 Pod Pending 按决策本轮不启动
- 未创建独立的系列导航页（系列链接完全内嵌在各文章正文），与前四篇一致的既有模式
