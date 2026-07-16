# Internal Publish Checklist — CrashLoopBackOff v1.0

**用途**：本文档是 `CRASHLOOPBACKOFF_OFFICIAL_ARTICLE_FINAL_DRAFT_v1.0.md` 的配套内部笔记，承载所有不该出现在对外文章正文里的部署元数据、历史状态、发布 blockers 和验证依据。对外文章正文经过本次清理已不再包含这些内容（详见该文件顶部说明），本文档是它们的唯一保留位置。

---

## 简短 Changelog

**2026-07-16（编辑反馈：删除 patch 段落的生产环境提醒）**
- 删除"修复思路"一节末尾提醒"生产环境不建议直接 patch 线上 Deployment，应回到 YAML/Helm/GitOps 源头修正"的 blockquote——owner 反馈这段在教程节奏里显得突兀，读者已经清楚这是配套实验的隔离环境，不需要额外的合规提醒打断阅读。同步更新已发布到 Directus 的正式文章内容（`id=4`），移除同一段落。技术表述本身没有错误，纯粹是编辑/节奏取舍，本条目下方"技术表述修正记录"第 2 条据此作废（保留记录，不删除历史，标注为已撤销）
- 未修改 lab、CTA 生产字段、`article_url`；仅更新 Directus 文章 `content` 字段与本地 final draft 正文

**2026-07-15（本轮：First Wave Article Publish Polish）**
- 开头"kubectl apply 返回成功"表述修正为"只说明对象被 Kubernetes 接收，不代表容器已经稳定运行"，避免暗示 apply 成功等于容器健康
- `kubectl patch` 长 JSON Patch 命令行在正文中改为简化展示（`-p='[ ... 替换 command 字段 ... ]'`），完整命令保留在配套实验中，正文改用文字解释这条命令做的事情，避免核心命令在文章里横向滚动
- "排查心智模型"从 ASCII 流程图（代码块）改为纯文字决策树（两条要点列表），更符合文章体裁的速读需求，而非实验手册体裁
- CTA 版本命名从 `internal_draft_note` 统一改为 `internal_preview_version`（与 Service 无 Endpoints / ImagePullBackOff 两篇保持一致的命名）
- 未修改 lab、Directus、CTA 生产字段，未发布文章

**2026-07-15（Polish for Public Draft）**
- 开头症状段改写为具体场景（"刚 apply 完新版本、以为没事了"），提升读者代入感，技术主线（describe/logs/logs --previous/patch/rollout status）未变
- "ImagePullBackOff RESTARTS 恒为 0"改为更严谨的表述——大多数情况下长时间为 0，因为镜像未拉取成功、容器根本未曾正式启动（正文与"排查心智模型" ASCII 图两处同步修正）
- "配套实验"段落拆分为 `internal_draft_note`（当前生效）与 `public_publish_version`（发布后启用的 CTA 文案占位草稿，当前未生效）两个版本，方便未来切换时直接替换，不用临时现写
- 未修改 lab、Directus、CTA，未发布文章

**2026-07-15（上一轮：Cleanup 拆分）**
- 从原 v1.0 混合稿中拆出本内部笔记文件，对外文章正文只保留读者向内容
- 同步完成两处技术表述修正（"RESTARTS 涨=CrashLoopBackOff"软化、patch 段落补充生产环境指导）

---

## 元数据

```
article_status: ready_to_publish_draft   # 不是 published，也不是 cta_enabled
article_url: null
cta_enabled: false
target_directus_article_id: null   # 未创建/复用任何 Directus 记录，本文档是内容草稿，不是已上线内容
lab_id: bb4fe651-7687-4457-9056-885172d9017b
source_article_id (LabGen 内部草稿, 非 Directus): e6d58c93-e093-4b32-9bee-04e2758f3ef1
lab_title: Kubernetes CrashLoopBackOff 排查实验：用 describe 和 logs 定位容器启动失败原因
lab publish_status（当前生产实际值，2026-07-15 核对）: published
```

本文档只是内部笔记，**不**通过 Directus/CTA 工具对外发布，不修改任何生产 lab/article-draft 字段。

---

## HIGH-01 历史状态漂移记录

该 lab 对应的文章曾于 2026-06-28 短暂发布过一版（`OWNER_SOFT_LAUNCH_ARTICLE1_PUBLISHED_VERIFIED_v0.1.md`，`cta_enabled=true`），随后在 2026-07-01 被人工/脚本改回 draft 状态、`published_at` 未同步清空，形成数据漂移，已于 2026-07-14 作为 HIGH-01 修复（详见项目内部记录）。当前生产状态是 `cta_enabled=false`、`article_url=null`，与另外两篇文章完全一致。当前的对外文章正文是基于当前真实 lab 内容重新整理的最终定稿，**不假设**旧版已发布文章的文字仍然准确，正文全部依据 `data/lab_drafts.json` 中当前生效的 7 个步骤重新核对。

---

## 发布前 blockers（未满足，不允许标记为 published）

1. `article_url` 为空 —— 尚未在 Directus 创建正式文章记录（该 lab 此前有过一次已发布又被回退的历史，本次为重新起草，不复用旧的 Directus 文章记录）
2. `cta_enabled=false` —— CTA 未对外暴露，对外文章"配套实验"段落里的引导文字是占位性质，不能上线成死链接或误导性 CTA
3. 真实学生对该 lab 仍 403（`LABGEN_ENABLED_LAB_IDS` 未包含此 lab_id）—— 文章一旦公开发布但学生点不进实验，会造成负面体验，因此文章发布必须晚于或同步于白名单开放决策，不能抢跑
4. 对外文章正文未经过真实读者可读性 review（不同于 lab #2 已完成的 dry-run review）——正文措辞、代码块格式、CTA 文案均需在发布前人工二次编辑
5. 与已发布的 Service 无 Endpoints / ImagePullBackOff 两篇文章一起排版发布时，需人工确认三篇文章之间的互相引用链接（正文"排查心智模型"段落分别提到了对方）不出现死链接

## Directus 旧记录复用/弃用决策点

该 lab 曾在 2026-06-28 短暂 `cta_enabled=true` 发布过一版旧文章，后于 2026-07-01 回退为 draft（HIGH-01），2026-07-14 已修复数据漂移。若未来重新发布，需人工确认旧的 Directus 文章记录（slug `crashloopbackoff-describe-logs`，若仍存在）与本次新草稿的关系（复用改写还是弃用新建），不能默认沿用旧记录的 `published_at`/`cta` 字段。这是一个需要 owner/CEO/CTO 明确拍板的决策点，不属于本次拆分任务的处理范围。

## CTA / 白名单 / student 403 状态（2026-07-15 核对）

| 项 | 值 |
|----|-----|
| `cta_enabled` | `false` |
| `article_url` | `null` |
| `LABGEN_ENABLED_LAB_IDS` 是否包含本 lab | 否（当前为空） |
| 真实学生访问该 lab | 403 |
| `data/labgen_invites.json` | 不存在 |

## 与 lab 功能性验证的关系（诚实记录）

对外文章描述的每一条命令、每一段 `describe`/`logs` 输出示例，均来自 `data/lab_drafts.json` 中当前生效的 7 个步骤（`rehearsal_completed: true`，全部 19 项 `validator_results` 为 `passed`，含 `explain.verified_if_published` 检查），退出码 127、`Back-off restarting failed container` 等具体细节直接取自该 lab 各步骤的 `observe`/`explain.observation` 字段，不是凭经验编写的推测性内容。本文档未新增或修改任何 lab 内容，仅将既有的、已验证的 lab 步骤数据转写为面向读者的文章体裁。

---

## Article-Lab Alignment（本次拆分复核）

对外文章正文（拆分/改写后）与当前 lab 7 步骤逐项对照：

| 对外文章段落 | 对应 lab step | 一致性 |
|--------------|---------------|--------|
| 症状 + 判定依据（RESTARTS 持续增加） | step-1（创建）+ step-2（观察 STATUS/RESTARTS） | 一致 |
| describe 看 Last State/Exit Code | step-3（describe，Exit Code 127） | 一致 |
| logs / logs --previous | step-4 | 一致 |
| 修复思路（patch） | step-5（patch） | 一致；正文改为简化命令展示 + 文字说明这条命令的作用（完整命令未变，仍与 lab step-5 的 JSON Patch 完全一致，只是不在文章正文里展开全文）。曾短暂新增过一段"生产环境应回归 YAML/Helm/GitOps"的补充说明，2026-07-16 已按 owner 编辑反馈撤销（见上方 Changelog），lab 本身自始至终未变，仍按原样使用 `kubectl patch` 做非交互式修复演示 |
| rollout status | step-6 | 一致 |
| （不写入对外文章正文） | step-7（cleanup，命名空间随「完成实验」自动回收） | cleanup 属于 lab session 生命周期管理，按拆分任务要求不需要写进对外文章正文，且未与 lab 实际行为冲突 |

**结论**：PASS，本次拆分/改写未引入与 lab 的不一致。

## 技术表述修正记录（本次拆分同步完成）

1. **"RESTARTS 涨就是 CrashLoopBackOff" → 软化为条件性表述**：原文"先看 RESTARTS 是不是在涨，涨就是 CrashLoopBackOff"是绝对化表述，改为"RESTARTS 列持续增加，通常说明容器已经启动过并进入了重启循环——这时候应该继续查 Last State/Exit Code/logs --previous"，避免暗示"RESTARTS 增加"是 CrashLoopBackOff 的充分且唯一判定条件。
2. ~~**patch 段落补充生产环境指导**：新增一段明确说明配套实验里用 `kubectl patch` 是为了在隔离环境里做非交互式演示，生产环境不建议直接 `patch` 线上 Deployment，应回到 Deployment YAML / Helm values / GitOps 源头修正，避免读者把实验里的演示手法直接照搬进生产操作。~~ **已于 2026-07-16 撤销**：owner 反馈这段在教程正文里显得突兀、打断阅读节奏，读者已通过"配套实验"框架清楚这是隔离练习环境，不需要额外合规提醒。技术表述本身无误，纯编辑取舍，见上方 Changelog。

---

## No Production Change Confirmation（2026-07-15）

| 检查项 | 结果 |
|--------|------|
| Directus 是否变更 | 否 |
| LabDraft 字段是否变更 | 否 |
| CTA 是否变更 | 否（`cta_enabled` 仍为 `false`） |
| access policy 是否变更 | 否 |
| lab publish_status 是否变更 | 否（仍为 `published`） |
| `LABGEN_ENABLED_LAB_IDS` 是否变更 | 否 |
| 是否新增 public exposure | 否 |
| 代码是否变更 | 否（本次仅涉及 docs 目录下的 `.md` 文件） |

---

## Publish Polish 检查结果（2026-07-15）

| 检查项 | 结果 |
|--------|------|
| title_style | PASS — "Pod 一直重启？从 CrashLoopBackOff 学会用 describe 和 logs 定位根因"，与另外两篇一致的"疑问句+排查线索"结构 |
| pain_point_opening | PASS — "kubectl apply 返回成功"表述本轮已修正为"只说明对象被接收，不代表容器稳定运行" |
| code_block_readability | PASS — `kubectl patch` 长 JSON Patch 命令本轮已改为简化展示 + 文字解释，完整命令保留在配套实验中 |
| cta_dual_version | PASS — `internal_preview_version` / `public_publish_version` 两个版本，命名已与另外两篇统一 |
| no_internal_metadata | PASS — 元信息块、blockers、HIGH-01、source_article_id 等已全部移至本文档 |
| lab_alignment | PASS（见上表） |
| publish_ready_for_owner_review | PASS |
