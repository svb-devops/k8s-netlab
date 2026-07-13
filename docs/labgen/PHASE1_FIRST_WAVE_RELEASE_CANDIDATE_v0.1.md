# Phase 1 First Wave Release Candidate v0.1

## 状态

`RC_SNAPSHOT` —— 本文档是收口性质的现状快照，供 Owner 决策使用。不改变任何 lab/article 的发布状态、不修改 `LABGEN_ENABLED_LAB_IDS`、不新增用户、不开放公开发布。本次 sprint 全程只读（除一处只读 dry-run，见 Health/Data 章节）。

---

## Series

```
series_name: Kubernetes 常见故障排查实战系列 / Kubernetes Troubleshooting Guided Labs
product_promise: 读文章，马上做一次真实的 Kubernetes 故障排查——不是看着代码猜，是在真实 K3s 集群里亲手复现故障、用 kubectl 工具链定位根因、验证修复生效
target_users: 正在学习/巩固 Kubernetes 排查技能的工程师（新手到中级），搜索具体报错状态（CrashLoopBackOff/ImagePullBackOff/Endpoints 为空）时的读者
runtime_scope: 单命名空间、single K3s runtime（不涉及多 VM / 多节点）
```

## First Wave Labs（3/3 已完成生产）

### 1. CrashLoopBackOff

| 字段 | 值 |
|------|-----|
| lab_id | `bb4fe651-7687-4457-9056-885172d9017b` |
| publish_status | `published` |
| static_validator | 20/20 PASS |
| rehearsal | 完成，`rehearsal_completed=true` |
| smoke | 完成（owner-as-learner） |
| cleanup_verified | `true`（历史记录，`OWNER_SOFT_LAUNCH_ARTICLE1_PUBLISHED_VERIFIED_v0.1.md`） |
| article draft status | **Directus `status=draft`**（article_id=4，slug=`crashloopbackoff-describe-logs`）——见下方"三篇文章一致性检查"关键发现 |
| CTA status | LabDraft 层 `cta_enabled=true`，`article_url` 已设置且指向上述 Directus 文章；但该 Directus 记录当前是 `draft` 状态，`GET /api/articles/{slug}` 返回"文章不存在"（404 语义），匿名访客访问该链接会看到空白/报错页面 |
| current access status | 真实学生仍 403（`LABGEN_ENABLED_LAB_IDS` 未包含此 lab_id，与 CTA/article 状态无关，gate 本身未受影响） |

### 2. Service No Endpoints

| 字段 | 值 |
|------|-----|
| lab_id | `2dcc7b1f-a52f-4a8f-9e8a-3ee9ff0a5a86` |
| publish_status | `published` |
| static_validator | 20/20 PASS |
| rehearsal | 完成，session `3bc6a420-2000-425b-bca3-398d56113dc2` |
| smoke | 完成，session `4aa8175d-4eaa-48f0-a1f8-a4c297e84df5`（learner） |
| cleanup_verified | `true` |
| article draft status | `ready_to_publish_draft`，`docs/labgen/SERVICE_NO_ENDPOINTS_OFFICIAL_ARTICLE_DRAFT_v0.1.md`，未创建 Directus 记录 |
| CTA status | LabDraft 层 `cta_enabled=false`，`article_url=null`（内部一致，无悬空链接风险） |
| current access status | 真实学生仍 403 |

### 3. ImagePullBackOff

| 字段 | 值 |
|------|-----|
| lab_id | `eb78afaa-f7fb-422e-8eb9-98644f59527f` |
| publish_status | `published` |
| static_validator | 20/20 PASS |
| rehearsal | 完成（两轮，第二轮 7/7 PASS），session `ff32289f-a891-4cbe-a70d-2a947724b06b` |
| smoke | 完成，session `d5a6abfe-f6b0-43a2-a57d-56657250ff42`（learner） |
| cleanup_verified | `true` |
| article draft status | `ready_to_publish_draft`，`docs/labgen/IMAGE_PULL_BACKOFF_OFFICIAL_ARTICLE_DRAFT_v0.1.md`，未创建 Directus 记录 |
| CTA status | LabDraft 层 `cta_enabled=false`，`article_url=null`（内部一致，无悬空链接风险） |
| current access status | 真实学生仍 403 |

---

## 三篇文章一致性检查

| 检查项 | CrashLoopBackOff | Service No Endpoints | ImagePullBackOff |
|--------|-------------------|------------------------|---------------------|
| 标题风格统一 | `Kubernetes Pod 启动失败溯查：从 CrashLoopBackOff 学会 kubectl describe 和 logs` | `Kubernetes Service 建好了但访问不通？大概率是 Endpoints 为空` | `Kubernetes Pod 卡在 ImagePullBackOff？先看 RESTARTS 是不是 0` |
| 真实痛点开篇 | 是（症状描述） | 是（症状描述） | 是（症状描述） |
| 不概括实验成果 | 是 | 是 | 是 |
| 不夸大 LabGen 能力 | 是 | 是 | 是 |
| 不提示普通用户可自由启动实验 | 是（"动手练习"段落未声明公开可用） | 是（明确写"内部验证阶段，尚未对外开放"） | 是（明确写"内部验证阶段，尚未对外开放"） |
| 与真实 lab 步骤一致 | 是（7 步与草稿逐条对应） | 是（7 步与草稿逐条对应） | 是（7 步与草稿逐条对应，含 rehearsal 中修正的两处细节） |

**标题风格不完全统一**：CrashLoopBackOff 用的是"溯查体"命名（更像正式发布稿），Service/ImagePullBackOff 两篇是我在生产 lab 时草拟的"排查实验体"命名（更像内部工作稿）。三篇正式对外发布前建议统一风格——具体采用哪种由 owner 决定，不在本次 RC 范围内擅自改写。

**关键发现（本次 RC 检查中发现，非本次改动引入）**：`OWNER_SOFT_LAUNCH_ARTICLE1_PUBLISHED_VERIFIED_v0.1.md`（2026-06-28 锁定）记录 CrashLoopBackOff 文章已 `PUBLISHED_VERIFIED`、`cta_enabled=true`，但实际查询 Directus（`GET /items/articles/4`）显示当前 `status=draft`，公开只读 API（`GET /api/articles`、`GET /api/articles/{slug}`）均确认该文章当前不可被匿名访客读取。也就是说这篇文章在 2026-06-28 之后的某个时间点从 `published` 被改回了 `draft`（本次未追查具体是谁在何时改的——不在本次只读 RC 快照范围内），但 LabDraft 层的 `cta_enabled`/`article_url` 字段没有同步更新，仍然指向这个现在实际上不可访问的文章。详见下方 Risk Register HIGH-01。

---

## CTA / Access 策略菜单（仅输出，不执行）

### A. Internal Closed
- 所有 lab 继续关闭给普通学生
- 三篇文章全部保持 draft
- CTA 全部 disabled（含 CrashLoopBackOff——需要 owner 决定是否把它也降回一致状态）
- 优点：零风险，维持现状
- 缺点：Phase 1 First Wave 的价值完全没有被任何真实读者验证过

### B. Owner Dogfood（推荐）
- Owner 自己以 learner 路径走完 first wave 三个 lab（不是 admin 身份绕过，而是走真实 learner 会话/步骤check/complete 全流程，与本次 sprint 里的 owner-as-learner smoke 同等严格度）
- 不需要任何外部真人
- 作为 Phase 1 的主验证方式：三个 lab 的机器化验证（rehearsal + smoke）已经完成，Owner Dogfood 补的是"人读文章 → 点 CTA → 做实验 → 读完成提示"这个完整读者旅程的主观体验校验，机器验证覆盖不到的措辞/节奏/困惑点
- 优点：零外部风险，且是机器化验证之外唯一能发现"读者视角问题"的手段
- 缺点：仍然是单一视角（owner 对内容太熟悉，可能低估新手会卡在哪里）——已知局限，不是本次要解决的问题

### C. Controlled Micro Invite
- 机制已就绪（`InviteRegistry`，`data/labgen_invites.json` + `LABGEN_ENABLED_LAB_IDS` 双开关）
- 面向未来 1-2 位具名可信用户的小范围邀测
- **本次不启用**——CEO/CTO 已明确本次严格禁止开放任何真实学生访问

### 推荐意见

**推荐 Owner Dogfood，不推荐现在开放外部测试。** 理由：机器化验证（static validation + rehearsal + smoke）已经对三个 lab 的功能正确性给出了高置信度信号，当前缺的不是"功能能不能跑通"，而是"读者会不会被文章措辞或实验节奏卡住"——这个缺口只有真人走一遍读者旅程才能补上，而 Owner Dogfood 是能补上这个缺口、同时零外部风险的最小手段。跳过它直接开放外部测试，会把"读者体验是否顺畅"这个未知变量和"是否要对外暴露"这个更大的决策捆在一起下注，没必要。

---

## Health / Data 状态快照

```
service_health: healthy（顶层 status=healthy，proxmox.connected=true，labgen.status=ok，email.status=ok）
recent_error_logs: 无（journalctl -p err --since "24 hours ago" 无条目）
git_status: clean，本地/远端 main = 6e64c81
```

**sessions 段 degraded**（非本次改动引入，pre-existing）：
```
zombie_draft_count: 19
lab_review_diffs_size_mb: 0.49（远低于 1MB 告警线）
```

已用 `DataRetentionService.run(dry_run=True)` 只读确认（未执行，未归档任何数据）：

```
lab_drafts_archived (would-be): 19
lab_review_diffs_archived (would-be): 230
llm_audit_entries_archived (would-be): 0
lab_runtime_entries_archived (would-be): 0
```

`DataRetentionService._get_protected_draft_ids()` 只保护 `publish_status=published` 或 `rehearsal_completed=true` 的草稿——三个 first wave lab 均满足保护条件，即使未来执行 retention 也不会被误清理。本次严格遵循任务边界：**只记录，不执行 retention，不新写 retention 代码**，这不构成 First Wave RC 的 blocker 或 high（19 个 zombie draft 是 demo/测试遗留草稿，与三个 first wave lab 无关）。

---

## 结论

`PHASE1_FIRST_WAVE_RC_READY_FOR_OWNER_DOGFOOD`

三个 lab 的功能性交付（static validation / rehearsal / smoke / cleanup）已全部完成且状态一致、健康。RC 阶段发现的唯一实质性问题是 CrashLoopBackOff 文章的 Directus 状态与 LabDraft CTA 字段不同步（HIGH-01，见 Risk Register），这是历史遗留状态漂移，不是本次三个 lab 生产工作引入的新问题，也不影响三个 lab 本身的功能正确性或访问收紧策略。建议下一步是 Owner Dogfood（见 `OWNER_DOGFOOD_FIRST_WAVE_RUNBOOK_v0.1.md`），HIGH-01 的处理（是否重新发布该文章、还是把 CTA 字段降回与另外两篇一致的关闭状态）留给 owner 单独决策。
