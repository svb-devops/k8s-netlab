# Service Official Article Publish Gate — 发布决策准备 v0.1

**Gate**: Service Official Article Publish Gate（发布决策准备，非发布执行）
**Status**: SERVICE_ARTICLE_READY_FOR_OWNER_PUBLISH_DECISION
**Date**: 2026-07-13
**Executed by**: Claude Code
**Branch**: main

本文档只做**发布决策准备**：审查文章草稿、设计 CTA 策略、输出 Directus 发布计划、完成读者可读性 review、输出访问策略矩阵。**不执行**任何实际发布、不修改 `LABGEN_ENABLED_LAB_IDS`、不创建 Directus 记录、不开放任何真实访问。

---

## 1. Official Article Final Draft Review

**审查对象**：`docs/labgen/SERVICE_NO_ENDPOINTS_OFFICIAL_ARTICLE_DRAFT_v0.1.md`

### 1.1 内容与真实 lab 一致性核对

逐项对照文章草稿与 `data/lab_drafts.json`（lab_id=`2dcc7b1f-a52f-4a8f-9e8a-3ee9ff0a5a86`）真实步骤：

| 文章段落 | 真实 lab 步骤 | 一致性 |
|---------|--------------|--------|
| 症状描述（Pod Running 但访问不通） | step-1/step-2（namespace/service 就绪） | ✅ 一致 |
| 第一步 `kubectl get endpoints web-svc` | step-2（`service_exists`） | ✅ 命令一致 |
| K3s `describe service` Endpoints 字段不可靠提醒 | RUNBOOK.md 已记录的已知限制 | ✅ 与本次 `service_has_endpoints` 实现的设计依据完全一致（verifier 也刻意不用该字段） |
| 第二步 `kubectl describe service web-svc` | step-3 | ✅ 一致，selector 值 `app=web-svc` 与草稿真实数据一致 |
| 第三步 `kubectl get pods --show-labels` | step-4（`app=web-backend` 标签） | ✅ 一致 |
| 第四步 `delete service` + `expose deployment` | step-5（RBAC 设计原因说明也一致：无 update/patch） | ✅ 一致 |
| 第五步验证 `kubectl get endpoints` | step-6（现已挂 `service_has_endpoints` verify） | ✅ 一致，且现在有机器化校验兜底 |
| 排查心智模型 | 与全部步骤逻辑吻合 | ✅ |

**结论**：文章草稿的命令、现象、修复路径与真实 lab 完全一致，无需修改正文技术内容。`service_has_endpoints` verifier 补齐后，文章第五步描述的"验证修复"现在有真实机器校验支撑，不再是纯人工 observe——这提高了内容可信度，但不需要改动文章措辞（文章面向读者，不暴露实现细节）。

### 1.2 语气与承诺边界核对

| 检查项 | 结果 |
|-------|------|
| 是否暗示普通读者现在可以自由启动实验 | ✅ 否——"配套实验"段落明确写"该实验目前处于内部验证阶段，尚未对外开放注册用户访问" |
| 是否暗示已上线能力 | ✅ 否——`article_status: ready_to_publish_draft`，`cta_enabled: false` 元信息已声明 |
| 是否夸大 AI 自动生成能力 | ✅ 否——正文全程未提及 LLM/AI 生成，只讲故障排查方法论 |
| 标题是否为搜索导向、非课程目录腔调 | ✅ 是——"Kubernetes Service 建好了但访问不通？大概率是 Endpoints 为空" 符合痛点导向 |

### 1.3 本轮更新

- **发布前 blocker #4**（"本文档从未经过真实读者可读性 review"）：本轮已完成 dry-run review（见第 4 节），文档已更新为"已完成，见第 4 节，遗留 MEDIUM 项未处理"，不再是完全空白状态，但**仍不构成可以发布的理由**——因为 blocker #1/#2/#3（Directus 记录、CTA 开放、学生白名单）均未变化。
- 未新增/未移除其它 blocker。

**文档变更**：已同步更新 `SERVICE_NO_ENDPOINTS_OFFICIAL_ARTICLE_DRAFT_v0.1.md` 的 blocker #4 状态（见该文件本次 diff）。

---

## 2. CTA Strategy Draft

**目标 lab_id**：`2dcc7b1f-a52f-4a8f-9e8a-3ee9ff0a5a86`
**当前 `cta_enabled`**：`false`（数据库真实值，本次未修改）

### 2.1 拟定 CTA 文案

调用了现有 `_build_cta()`（`backend/labgen/routes.py`）生成的真实输出（只读调用，未落库、未对外暴露）：

```
markdown_cta:
> 配套实验：[Kubernetes Service 无 Endpoints 排查实验：selector 与 labels 不匹配](https://lab.cloudnetops.tech/labgen-lab.html?labId=2dcc7b1f-a52f-4a8f-9e8a-3ee9ff0a5a86)
> 无需本地环境，浏览器直接练习，完成后自动销毁。

copyable_text:
本文配套实操实验已上线，无需安装任何环境，在浏览器中直接练习：
点击进入实验 → Kubernetes Service 无 Endpoints 排查实验：selector 与 labels 不匹配
https://lab.cloudnetops.tech/labgen-lab.html?labId=2dcc7b1f-a52f-4a8f-9e8a-3ee9ff0a5a86
实验完成后环境自动销毁，数据不保留。
```

### 2.2 ⚠️ HIGH 风险发现（本轮 review 新发现，非本次改动引入）

`_build_cta()` 是**通用模板**，只要 `draft.publish_status == PUBLISHED` 就无条件生成"本文配套实操实验**已上线**"这句话——它不检查 `LABGEN_ENABLED_LAB_IDS`。也就是说：**如果此刻不假思索地把这段文案贴到公开文章里，文案本身就是一句谎言**——该 lab 并未真正对学生开放。

更进一步，本轮 review 发现这个问题不止存在于 CTA 文案生成层，**学员目录 API 本身也有同样的盲区**（见第 6 节 HIGH-001）：已登录的真实学生现在浏览实验目录时，这个 lab 已经以 `is_startable=true` 的状态出现在列表里，点击详情页也看不到任何"暂未开放"的提示，只有真正点击"开始实验"才会收到 403。**这与 CTA 是否开放无关，是已存在的独立问题**，但直接放大了"CTA 一旦贴出去，用户点进来会先看到一个看起来能开始、实际点了才 403"的体验风险。

### 2.3 未开放白名单情况下，普通用户点击 CTA 会发生什么（当前真实行为，已用真实 API 验证）

1. 未登录用户点击 CTA 深链 → 命中前端登录墙，跳转登录/注册页（不是本次改动范围，行为未变）
2. **已登录的真实学生**点击 CTA 深链 → 进入 lab 详情页，页面显示 `is_startable=true`，**没有任何"未开放"提示**（HIGH-001，见第 6 节）→ 点击"开始实验"按钮 → 后端 `POST /lab-sessions` 返回 403（`LABGEN_ENABLED_LAB_IDS` 网关生效）→ 前端目前对此 403 的呈现方式未在本轮验证范围内，需要另行确认前端是否有得体的错误提示

**结论：在 HIGH-001 修复之前，即使只是把 CTA 挂到文章里（不改动能否点进 403 之前的任何门禁），已登录学生也会先看到一个"看起来能开始"的详情页，这是一个用户体验/信任问题，不是安全问题（403 仍然生效，未泄露任何数据）。**

### 2.4 未来 controlled invite 时，白名单用户点击 CTA 的预期行为

一旦 `LABGEN_ENABLED_LAB_IDS` 包含该 lab_id 且用户在邀测名单内：CTA → 登录 → 目录可见 → 详情页 `is_startable=true` → 点击开始 → `POST /lab-sessions` 成功 → 正常进入 7 步实验流程（已在此前 sprint 用真实 K3s rehearsal + learner smoke 验证过 7/7 通过）。这条路径本身没有问题。

### 2.5 CTA 文案安全边界核对

| 检查项 | 结果 |
|-------|------|
| 暴露 `source_article_id` | ✅ 否——`_build_cta()` 从未引用该字段 |
| 暴露 prompt / LLM 原始输出 | ✅ 否 |
| 暴露 API key / 内部路径 | ✅ 否 |
| 文案本身声称"已上线"但实际未对该学生开放 | ⚠️ 是（第 2.2 节问题，需在真正启用 CTA 前修复文案条件判断或先完成白名单开放） |

---

## 3. Directus / Article Publish Plan

**结论：本次不创建任何 Directus 记录，只输出计划。**

调用只读检查确认 Directus 服务当前状态（未修改任何数据）：

```
$ curl -s http://127.0.0.1:8055/server/info | jq .data.project.project_name  → 可达
articles 集合已存在（welcome-to-k8s-netlab 等既有已发布文章）
```

### 3.1 Directus articles 集合是否支持 draft/private 状态

已确认（`backend/labgen/articles_routes.py` + `scripts/setup_directus.py` 既有实现）：`articles` 集合的 `status` 字段支持 `draft`/`published`（Directus 标准状态机），且现有 Public Policy 只对 `filter[status]=published` 开放匿名读取。**因此 Directus 支持在 draft 状态下创建记录而不对外暴露。**

### 3.2 发布计划（按 Directus 支持 draft 状态执行）

由于本次任务明确"不做任何发布"，即使 Directus 支持 draft，**本轮也不创建记录**（避免在没有 owner 最终拍板前产生任何可能被误操作 flip 成 published 的实体）。

**发布 checklist（供 owner 决策后执行，本次仅输出，不执行）：**

1. 在 Directus 后台以 `status=draft` 创建 `articles` 记录，`title`/`slug`/`excerpt`/`content` 填入 `SERVICE_NO_ENDPOINTS_OFFICIAL_ARTICLE_DRAFT_v0.1.md` 正文（已完成 1.1 节一致性核对）
2. 记录创建后的 `directus_id` 回填到 `LabDraft.article_url`/`article_title`（通过既有 `PATCH /drafts/{id}` 端点，admin-only），使 `_build_cta()` 生成的 CTA 里 `article_url` 字段不再是 `null`
3. **在解决第 6 节 HIGH-001（目录可见性未按白名单收紧）之前，不建议将 `draft.cta_enabled` 置为 `true`**——即使文章还是 draft，`cta_enabled` 一旦为 true 就会在学员详情页暴露 `article_url`/`article_title`（见 `learner_catalog.py::get_published_lab_detail` 的 `if cta_enabled:` 分支）
4. Owner 决定 `LABGEN_ENABLED_LAB_IDS` 开放策略（见第 5 节 Access Matrix）后，再决定 Directus 记录 `status` 是否 flip 为 `published`
5. `article_url`/`article_channel` 校验：`check_article_lab_consistency()` 已在 `_build_cta()` 中自动跑一次一致性检查（本次调用返回 `topic_consistency_warning=None`，即当前 `article_title` 与 lab 主题一致，无需额外处理）

**输出**：
- `directus_id`: null（未创建）
- `article_url`: null（未创建）
- `article_status`: 未创建
- `reason_if_not_created`: 任务范围明确禁止本轮发布，且发现 HIGH-001 应在真正开放 CTA 前解决

---

## 4. Reader Dry-Run Review

**性质说明**：本次是**文章内容可读性 review**（对照 `LINUX_READER_FACING_CTA_DRY_RUN_RESULT_v0.1.md` 的方法论，但范围缩小为纯内容审查，不重跑完整 learner session E2E——lab 的功能性 rehearsal/learner smoke 已在此前 sprint 用真实 K3s 完整验证过 7/7 PASS，本次不重复）。由 Claude Code 以"完全不了解本项目内部实现、只有基础 K8s 知识的读者"视角逐句走读文章草稿。

### 4.1 可读性走读结果

| 检查项 | 结果 | 备注 |
|-------|------|------|
| 能否理解"为什么 Service 没有 Endpoints" | ✅ 能 | "症状"段落用"Pod Running 但访问不通、日志无错误"精确描述了这个反直觉现象——读者最容易先去查 Pod 日志（症状段落已预判并纠正了这个错误直觉） |
| 能否理解 selector 与 labels 的关系 | ✅ 能 | 第二步/第三步先后展示 `describe service` 的 Selector 行和 `get pods --show-labels` 的 LABELS 列，"对比"动作被显式引导，不需要读者自己联想 |
| 是否知道下一步该做什么 | ✅ 知道 | 每步都有明确的下一条命令；"排查心智模型"段落把整个流程收敛成一张可复用的判断树，读完能内化为方法论而不只是记住一次案例 |
| 文章与 lab 步骤是否一致 | ✅ 一致 | 见第 1.1 节逐项核对 |
| 是否存在实验描述有问题 | ✅ 无问题 | "配套实验"段落措辞谨慎（"该实验目前处于内部验证阶段，尚未对外开放注册用户访问"），未使用"马上""立即"等催促性语言 |
| 是否存在夸大或暗示未上线能力的提示 | ✅ 无 | 未提及 AI/LLM，未使用"智能""自动生成"等词 |

### 4.2 发现的问题（MEDIUM/LOW，非 blocker）

**MEDIUM-CTA-01**：文章草稿本身没有问题，但如果按第 3 节计划把它塞进 Directus 并配合第 2 节生成的默认 CTA 文案一起发布，CTA 文案的"已上线"措辞与文章"尚未对外开放"的措辞会自相矛盾。**建议**：真正执行发布时，CTA 文案需要人工改写为条件性措辞（例如"实验邀测中，暂未对所有读者开放"），不能直接用 `_build_cta()` 的默认输出。

**LOW-01**：文章"配套实验"段落目前是纯文字提示，没有实际的 CTA 组件/链接（这是预期设计，`cta_enabled=false`），发布时需要人工二次编辑该段落，而不是假设它会自动变成可点击链接。

### 4.3 未发现的问题（明确核对过，结果良好）

- 无 `[TODO]`/占位符文本
- 无死链接（"配套实验"段落不含任何 URL）
- 无对读者当前账号状态的错误假设（未写"登录后即可开始"这类误导性引导）

---

## 5. Access Matrix

**本节只输出对比，不执行任何开放操作。**

| 维度 | A. 继续内部关闭 | B. Controlled Micro Invite |
|------|-----------------|----------------------------|
| 文章可见性 | 仅 draft，不发布 | article draft only（本轮方案不含文章公开发布） |
| Lab 学员访问 | `LABGEN_ENABLED_LAB_IDS` 不含此 lab_id，403 全员 | 1-2 位具名用户，仅 CrashLoopBackOff + Service-no-Endpoints 两个 lab |
| CTA 状态 | `cta_enabled=false` | 仍建议 `cta_enabled=false`（CTA 面向公开读者，与"1-2 位具名邀测用户"是两回事——邀测用户应通过直接告知 deep_link，而非公开 CTA） |
| Generation/admin 端点 | 学员侧本就不可达 | 保持不可达（学员 RBAC 已在此前 sprint 收敛为 services/endpoints 只读，未涉及 generation/admin） |
| Cleanup 监控 | 不需要（无活跃会话） | 需要——沿用 `smoke-test`/health 端点里的 `active_session_count`/`tainted_vm_count`/`zombie_draft_count` 监控 |
| 是否需要先解决 HIGH-001 | 不需要（学生本就 403，目录可见性问题不会被真实触发，因为目录里根本没有真实学生在关注这个 lab） | **需要**——邀测用户一旦被加入 `LABGEN_ENABLED_LAB_IDS`，目录可见性行为对他们就变成期望内行为（is_startable=true 且能真正 start），HIGH-001 反而不再是问题——**HIGH-001 只在"lab 已 published 但故意不在白名单里"这个中间状态下才是问题** |
| 风险 | 无新增风险，维持现状 | 用户规模小，可控；主要风险是内容质量（第 4 节已过 review）和 cleanup 残留监控 |

**本次不推荐执行选项，只输出对比矩阵供 owner 决策。**（`recommended_option` 留空，由 owner 基于本文档 + 此前 `LABGEN_CONTROLLED_INVITE_POLICY_v0.1.md` 综合决定）

---

## 6. Regression / Safety

| 检查项 | 结果 |
|-------|------|
| Service lab `publish_status` 保持正确 | ✅ `PUBLISHED`（本次 review 全程只读，未修改任何 draft 数据） |
| CrashLoopBackOff lab 不受影响 | ✅ 未触碰任何相关代码/数据 |
| `service_has_endpoints` verifier 仍可用 | ✅ 上一任务已验证，本次未改动 verifier 代码 |
| 学生访问仍 403 | ✅ `LABGEN_ENABLED_LAB_IDS` 本次未修改（本次任务未触碰 `.env`/`config.py`） |
| 公开暴露面无新增 | ✅ 未创建 Directus 记录、未开放 CTA、未修改任何权限配置 |
| health | ✅ `{"status":"healthy",...}` |
| targeted tests | ✅ 327 passed（static_validator/verifier/k8s_verifier_client/learner_catalog/draft_api） |
| mypy | ✅ 0 error |
| git status | ✅ clean（本次代码零改动，仅新增/更新 2 个 docs 文件） |

### HIGH-001（本轮新发现，独立于本次任务范围，记录以供后续处理）

**问题**：`LearnerCatalogService.list_published_labs()` / `get_published_lab_detail()` / `evaluate_start_eligibility()`（`backend/labgen/learner_catalog.py`）均只检查 `publish_status == PUBLISHED`，**不检查 `LABGEN_ENABLED_LAB_IDS`**。`LABGEN_ENABLED_LAB_IDS` 网关只在 `LabSessionService`（真正的 `POST /lab-sessions` 启动调用）里生效（`lab_session_service.py:280`）。

**实测（真实数据，只读调用，未创建任何会话）**：已登录学生视角调用 `list_published_labs(actor_user='some-real-student')`，Service-no-Endpoints lab 返回 `is_startable=true`；`get_published_lab_detail()` 的 `start_eligibility.is_startable` 同样为 `true`，`issues` 里没有任何提示白名单未命中。

**影响**：任何**已发布但未加入 `LABGEN_ENABLED_LAB_IDS`** 的 lab（当前正是 Service-no-Endpoints 的状态），已登录学生现在浏览目录时会看到它显示为"可开始"，实际点击"开始实验"才会 403。**未验证前端对该 403 的呈现方式**——如果前端只是显示通用错误而不解释原因，会造成困惑的用户体验。此问题**不是本次 sprint 引入的**，是 `LABGEN_ENABLED_LAB_IDS` 网关设计从一开始就只覆盖到 session 创建层、没有覆盖到目录层的既有 gap。

**是否安全问题**：不是——没有任何数据泄露或越权访问，403 网关本身仍然有效，只是"何时"暴露拒绝信息的时机比预期晚。

**建议处理方式**：作为独立 bug-fix 任务处理（`learner_catalog.py` 的 `is_startable`/`start_eligibility` 计算逻辑应该也纳入 `LABGEN_ENABLED_LAB_IDS` 判断，返回一个明确的 `not_in_whitelist` 类 issue，而不是让学生走到点击才知道），不在本次任务范围内修复。**如果 owner 决定推进 Controlled Micro Invite（方案 B），这个问题届时会自然消解**（因为受邀用户本来就该在白名单里）；**如果 owner 决定继续内部关闭（方案 A），这个问题当前不会被真实学生触发**（因为没有已登录学生在主动查看这个特定 lab_id），可以延后处理，但建议不要无限期搁置。

---

## Final Output

```yaml
service_article_publish_gate_handoff:
  overall_status: SERVICE_ARTICLE_READY_FOR_OWNER_PUBLISH_DECISION
  article:
    draft_path: docs/labgen/SERVICE_NO_ENDPOINTS_OFFICIAL_ARTICLE_DRAFT_v0.1.md
    title: "Kubernetes Service 建好了但访问不通？大概率是 Endpoints 为空"
    article_status: ready_to_publish_draft
    ready_for_publish_decision: true
    remaining_content_risks:
      - "CTA 默认文案（_build_cta()）与文章'尚未开放'措辞矛盾，真正发布时需人工改写 CTA 文案（MEDIUM-CTA-01）"
      - "发布前 blocker 1/2/3（Directus 记录、CTA 开放、学生白名单）仍未满足，未变化"
  cta_strategy:
    proposed_cta_text: "见本文档第 2.1 节 markdown_cta/copyable_text（_build_cta() 真实生成，未改写）"
    target_lab_id: "2dcc7b1f-a52f-4a8f-9e8a-3ee9ff0a5a86"
    current_cta_enabled: false
    expected_public_behavior: "未登录→登录墙；已登录未受邀→目录可见 is_startable=true（HIGH-001）→点击开始→403"
    expected_whitelist_behavior: "受邀用户→正常 7 步实验流程，此前 sprint 已用真实 K3s 验证 7/7 PASS"
  directus_plan:
    draft_created: false
    directus_id: null
    article_url: null
    status: not_created
    reason_if_not_created: "任务范围明确禁止本轮发布；且应先解决 HIGH-001 再考虑开放 CTA"
  reader_dry_run:
    readability: good
    pain_point_strength: good
    lab_alignment: consistent
    not_too_manual_like: true
    risks:
      - "MEDIUM-CTA-01: 默认 CTA 文案与文章测辞矛盾"
      - "LOW-01: 配套实验段落是纯文字，发布时需人工二次编辑"
  access_matrix:
    internal_closed: "见第 5 节表格 A 列"
    controlled_micro_invite: "见第 5 节表格 B 列"
    recommended_option: null   # 本次只输出矩阵，不做推荐执行
  regression:
    service_lab_status: published
    crashloopbackoff_status: unaffected
    service_has_endpoints: enabled
    student_access_still_403: true
    public_exposure: no_change
    health: healthy
    tests: "327 passed (targeted)"
    mypy: "0 error"
  issues:
    blocker: []
    high:
      - "HIGH-001: learner_catalog.py 的 is_startable/start_eligibility 未纳入 LABGEN_ENABLED_LAB_IDS 判断，已发布未白名单的 lab 在目录里显示可开始，直到真正点击 Start 才 403（详见第 6 节）"
    medium:
      - "MEDIUM-CTA-01: _build_cta() 默认文案在 lab 未真正开放时会声称'已上线'，发布前需人工改写（详见第 2.2/4.2 节）"
    low:
      - "LOW-01: 文章'配套实验'段落是纯文字提示，发布时需人工二次编辑为真实 CTA（详见第 4.2 节）"
  commits: []
  pushed_to_github: false
  git_status: clean
  recommended_next_step: >
    Owner 基于本文档第 5 节 Access Matrix 和 LABGEN_CONTROLLED_INVITE_POLICY_v0.1.md
    做出访问策略决策（继续关闭 / Controlled Micro Invite）。若选择推进邀测，建议先排期修复
    HIGH-001（目录可见性未按白名单收紧），再执行 Directus 发布 checklist（第 3.2 节）和
    CTA 文案人工改写（MEDIUM-CTA-01）。本次未创建任何对外可见实体，无需回滚。
```
