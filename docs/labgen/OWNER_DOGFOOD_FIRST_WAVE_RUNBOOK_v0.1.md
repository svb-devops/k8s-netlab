# Owner Dogfood — First Wave Runbook v0.1

## 状态

`documentation_only`。本文档只是给 owner 使用的操作手册，不代表 dogfood 已执行。执行 dogfood 时使用 owner 自己的账号，走真实 learner 路径（不是 admin 绕过），产出记录写回本文档或新建 `..._RESULT_v0.1.md`。

## 目的

机器化验证（static validation + rehearsal + smoke）已经确认三个 lab 的**功能正确性**：命令能跑通、verify 能通过、cleanup 能生效。Owner Dogfood 要验证的是机器测不出来的东西——**读者视角的体验**：文章措辞是否顺畅、实验步骤节奏是否合理、卡点提示是否够用、完成后的感受是否达到"学到了东西"的预期。

---

## 测试顺序

按 first wave 生产顺序进行，也是难度递进顺序（三者共享"Pod 状态类"故障诊断心智模型，按顺序做能感受到心智模型的复用）：

1. **CrashLoopBackOff** —— 先做这个，建立"Pod 反复重启 → 查 describe/logs → patch 修复"的基础心智模型
2. **Service No Endpoints** —— 对比"Pod 起来了但没流量"与上一个的区别
3. **ImagePullBackOff** —— 对比"Pod 从没起来过"与前两者的区别，检验三者放在一起读是否真的能形成互补而非混淆

## 每个 lab 预计耗时

| Lab | 文章阅读 | 实验操作 | 合计 |
|-----|---------|---------|------|
| CrashLoopBackOff | 5-8 分钟 | 15-20 分钟 | ~25 分钟 |
| Service No Endpoints | 5-8 分钟 | 15-20 分钟 | ~25 分钟 |
| ImagePullBackOff | 5-8 分钟 | 15-20 分钟 | ~25 分钟 |
| **三个合计** | | | **约 75 分钟**（建议不要一次做完，每个之间留间隔，更接近真实读者的阅读节奏） |

## 每个 lab 成功标准

- 文章读完后，不需要反复回看就能理解"症状是什么、为什么会这样、怎么查、怎么修"这四件事
- 实验每一步的 `do`/`observe` 文字与命令实际输出基本对应，不需要靠猜测才能继续下一步
- 遇到卡顿时，`troubleshoot` 字段提供的提示确实有帮助（不是泛泛而谈）
- 完成后有清晰的"我确实学会了"的感受，而不是"照着敲完命令但不知道为什么"

## 操作方式

三个 lab 均为 `publish_status=published` 但未加入 `LABGEN_ENABLED_LAB_IDS`。Owner 账号（`smoke-admin` 或其他 admin 账号）天然绕过该白名单网关（见 `run_precheck()`/`LearnerCatalogService` 的 admin bypass 逻辑），无需临时修改任何配置即可走完整 learner 路径：

1. 登录 admin 账号
2. 打开 lab 详情页（`https://lab.cloudnetops.tech/labgen-lab.html?labId=<lab_id>`）
3. 点击 Start Lab，走真实 `POST /api/lab-sessions` → `session_type=learner`（不要用 `/internal/rehearsal-sessions`，那是机器化验证路径，不代表读者体验）
4. 按文章内容逐步操作，记录任何"文章说的和实际看到的不一样"的地方
5. 完成后调用 `complete()`，确认 `cleanup_verified=true`

## 记录哪些反馈

按严重程度分类记录，不要笼统写"体验不错/不好"：

- **BLOCKER**：完全无法继续（命令报错且没有可行的 troubleshoot 路径）
- **HIGH**：能继续但会产生明显误解或挫败感（比如 Service No Endpoints 已知的 K3s `describe service` Endpoints 字段不可靠问题——这类必须提前在文章里预警）
- **MEDIUM**：不影响完成，但读起来别扭、或者步骤顺序可以更顺（比如某个 troubleshoot 提示信息量不够）
- **LOW**：纯措辞/格式建议，不影响理解

## 何时判定 PASS / PASS_WITH_NOTES / BLOCKED

```
PASS              — 零 BLOCKER，零 HIGH
PASS_WITH_NOTES   — 零 BLOCKER，允许 MEDIUM/LOW（不阻塞上线），HIGH 需逐条评估是否真的阻塞
BLOCKED           — 出现 BLOCKER，或 HIGH 累计到影响核心学习路径完整性
```

MEDIUM/LOW 不阻塞上线——记录下来留给下一轮内容迭代即可，不需要在 dogfood 完成后立刻回去改文章。只有 BLOCKER/HIGH 才需要在正式发布前处理。

## 待填写：Dogfood 执行结果

本次 sprint（Phase 1 First Wave RC Freeze）只交付本 runbook，不执行 dogfood 本身（CEO/CTO 本次任务边界：只冻结 RC，不启动新实验、不开放灰度）。以下表格留空，待 owner 实际执行后填写：

| Lab | 执行日期 | 判定 | BLOCKER | HIGH | MEDIUM | LOW | 备注 |
|-----|---------|------|---------|------|--------|-----|------|
| CrashLoopBackOff | — | — | — | — | — | — | 需先决定 HIGH-01（article Directus 状态与 CTA 字段不同步）如何处理，见 `PHASE1_FIRST_WAVE_RELEASE_CANDIDATE_v0.1.md` |
| Service No Endpoints | — | — | — | — | — | — | 已知 K3s `describe service` Endpoints 字段不可靠问题需在文章里提前预警（`SERVICE_NO_ENDPOINTS_OFFICIAL_ARTICLE_DRAFT_v0.1.md` 已包含此提醒） |
| ImagePullBackOff | — | — | — | — | — | — | rehearsal 中已修正的两处内容问题（错误消息文案、容器名假设）已同步进正式文章草稿，dogfood 时重点验证这两处修正后是否真的顺畅 |
