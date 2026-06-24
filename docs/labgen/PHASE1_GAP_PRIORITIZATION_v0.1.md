# Phase 1 Gap Prioritization v0.1

**Date**: 2026-06-24
**Operator**: Claude Code acting as senior dev + ops
**Status**: Authoritative P0/P1/P2 gap list for Admin-curated Article-to-Lab Phase 1
**No real secrets in this document.**

---

## Gap Classification Summary

| Priority | Gap | Impact | Blocker? |
|----------|-----|--------|---------|
| P0 | Article → Lab 绑定（article_url 字段缺失） | Admin 无法记录外部文章链接；CTA 无法双向验证 | Phase 1 flow 不完整 |
| P0 | Admin CTA 工具（无标准生成/复制工具） | 无法规模化发布文章+实验组合 | Phase 1 scale 受阻 |
| P1 | 邮箱注册字段缺失 | 无法推送通知、无法自助找回密码 | NOT 当前 Article→Lab 闭环的阻塞点 |

P0 为 Article → Lab 闭环的必要条件，必须在扩张前实现。P1 为 reader growth / retention 基础设施，重要但不是 P0 前置。

---

## P0 Gap 1：Article → Lab 绑定

### 问题描述

当前 `LabDraft` 模型只有 `source_article_id`（内部 UUID），没有存储外部发布文章的 URL 或元数据。

这导致：
- Admin 无法在系统中记录"这个 lab 对应哪篇微信/知乎文章"
- 系统无法验证 CTA deep link 与文章的对应关系
- 读者无法在 lab 完成后看到"回到原文"链接
- 文章发布后无法追踪"哪些 lab 被哪些文章引用了"

### 建议字段

以下字段加入 `LabDraft` 模型（均为 Optional，向后兼容）：

```python
article_url: Optional[str] = None
# 外部发布文章链接，例如：
# - https://lab.cloudnetops.tech/article.html?slug=k8s-configmap-basics
# - https://mp.weixin.qq.com/s/...（微信公众号）
# - https://zhuanlan.zhihu.com/p/...（知乎）
# - https://github.com/...（GitHub）

article_title: Optional[str] = None
# 文章标题（展示用，不一定等于 lab title）

article_channel: Optional[str] = None
# 发布渠道标识：website / wechat / zhihu / csdn / github / other

article_published_at: Optional[datetime] = None
# 文章发布时间

cta_enabled: bool = True
# 是否向读者展示 CTA 绑定（发布 lab 后默认为 True）
```

### 暴露约束

- `article_url`、`article_title`、`article_channel`、`article_published_at` **可以**通过 Learner API 返回（帮助读者找到原文）
- `source_article_id` **绝对不得**暴露给 Learner API（内部追踪 ID）
- 原始文章文本 **绝对不得**暴露给任何 API（版权和内容边界）

### 实现范围

修改文件（P0 不做代码变更，仅记录计划）：
- `backend/labgen/models.py`：`LabDraft` 加上述 5 个字段
- `backend/labgen/routes.py`：`PatchDraftRequest` 支持更新这 5 个字段
- `frontend/js/labgenClient.js`：`PATHS.patchDraft` 路径（当前缺失）
- `frontend/labgen-admin.html`：article URL 输入字段 + 保存按钮
- 无数据迁移（JSON 文件存储，新字段默认 None，旧记录自动兼容）

### 测试需求

- 新增：`PATCH /api/labgen/drafts/{id}` 含 `article_url` 字段更新测试
- 新增：Learner API 返回 `article_url` 测试
- 新增：`source_article_id` 不出现在 Learner API 响应中的负向测试

---

## P0 Gap 2：Admin CTA 工具

### 问题描述

CTA deep link 格式已定义（`/labgen-lab.html?labId=<uuid>`），但 Admin 当前没有工具生成标准化的 CTA 链接和嵌入文案。每次发文章都需要手工拼接 URL，没有标准的中文文案模板，容易出错，无法规模化。

### 建议 CTA 工具能力

以下 4 种格式的 CTA 生成，均在 Admin 页面一键复制：

**1. 纯链接（适合任意平台）**
```
https://lab.cloudnetops.tech/labgen-lab.html?labId=6c439064-4cad-4229-addb-36927128d565
```

**2. 标准中文文案（适合微信/知乎/CSDN 正文末尾）**
```
本文配套实操实验已上线，无需安装任何环境，在浏览器中直接练习：
👉 点击进入实验 → [Lab Title]
https://lab.cloudnetops.tech/labgen-lab.html?labId=<uuid>
实验完成后环境自动销毁，数据不保留。
```

注意：CTA 文案不得包含以下声明：
- "任意文章都能生成实验"
- "普通用户可以上传文章"
- "Live AI 已开放"
- "Production ready"
- "Public launch"

**3. Markdown CTA（适合 GitHub / 博客）**
```markdown
> **配套实验**：[Lab Title](https://lab.cloudnetops.tech/labgen-lab.html?labId=<uuid>)
> 无需本地环境，浏览器直接练习，完成后自动销毁。
```

**4. 网站 article.html 嵌入 CTA 块（标准 HTML 组件）**
```html
<div class="lab-cta-block">
  <p>本文配套实操实验已上线：</p>
  <a href="/labgen-lab.html?labId=<uuid>" class="btn-start-lab">[Lab Title]</a>
  <small>无需安装环境，完成后自动销毁</small>
</div>
```

### 实现范围

修改文件（P0 不做代码变更，仅记录计划）：
- `frontend/labgen-admin.html`：Published lab 详情区域加"复制 CTA 链接"按钮（4 种格式切换）
- `frontend/js/labgenViews.js`：`renderAdminDraftView` 加 CTA 生成逻辑
- `frontend/article.html`：如果 lab 有 `article_url` 绑定此文章，显示 lab-cta-block 组件

---

## P1 Gap 3：邮箱注册字段

### 问题描述

当前用户模型（`data/users.json`）只有以下字段：
```json
{
  "password_hash": "...",
  "created_at": "...",
  "assigned_vm": "..."
}
```

没有 `email` 字段。注册接口 `register_user(username, password)` 不接受 email 参数。

这影响：
- 无法向读者推送后续文章/实验通知（用户运营核心能力）
- 读者忘记密码无法自助找回（只能联系 admin 重置）
- 无法按用户群体分层运营（新文章定向推送）
- 未来 email 验证（防止机器人注册）

### 为什么是 P1 而不是 P0

email 注册是 reader growth / retention / notification 基础设施，属于**产品运营基础设施**，而非 Article → Lab 闭环（P0）的必要组件。

Article → Lab 的完整闭环是：
```
文章 CTA → 注册 → 进入实验 → 完成 → cleanup
```

这个闭环当前可以用用户名+密码注册完成，email 不是必须字段。

### 建议实现（P1 阶段）

- `register_user(username, password, email: Optional[str] = None)` 接口扩展
- `data/users.json` 用户对象加 `email` 字段（Optional，旧用户 null）
- 注册表单前端加 email 输入框（Optional，Phase 1 不强制验证）
- 后端格式校验：`@` 包含、基础格式检查（不发验证邮件，仅存储）
- 邮件推送服务（SendGrid / 阿里云 Email）：留到 P1 独立规划，不在此 gap 内

---

## Non-Gap Items（NOT missing，已有能力）

以下内容已实现，**不属于 gap，不需要重建**：

| 能力 | 实现状态 |
|------|---------|
| Admin article draft input | ✅ `POST /api/labgen/article-drafts` |
| Draft generation (Stub) | ✅ `LabDraftGeneratorStub` |
| Admin review / PATCH | ✅ `PATCH /api/labgen/drafts/{id}` |
| StaticValidator publish gate | ✅ 13-point check |
| Internal rehearsal | ✅ rehearsal_required / rehearsal_completed |
| Publish lab | ✅ `POST /api/labgen/drafts/{id}/publish` |
| Learner catalog | ✅ `GET /api/labs` + `labgen-catalog.html` |
| CTA deep link format | ✅ `/labgen-lab.html?labId=<uuid>` |
| Lab session start | ✅ `POST /api/lab-sessions` (6 precheck) |
| Step check (K8s) | ✅ K8sVerifierClientAdapter |
| Step check (Linux) | ✅ LinuxVerifierAdapter |
| Session complete + cleanup | ✅ LAB_CLOSED |
| VM taint recovery | ✅ tainted_vms.json |
| Homepage article list | ✅ `landing.html` + Directus CMS |
| Article detail page | ✅ `article.html` |
| Articles API | ✅ `GET /api/articles` |
| Reader comments | ✅ `POST /api/articles/{slug}/comments` |
| Lab format: K8s | ✅ 5 published K8s labs (G-34 verified) |
| Lab format: Linux | ✅ 1 published Linux lab (G-51 verified) |

---

## Issue Triage

| Level | Issue | Status |
|-------|-------|--------|
| P0 | `article_url` 字段缺失 → Admin 无法记录外部文章链接 | ✅ CLOSED — G-58 实现 |
| P0 | Admin CTA 工具缺失 → 发布文章需手工拼 URL | ✅ CLOSED — G-58 实现 |
| P1 | 邮箱字段缺失 → 无法推送通知/找回密码 | ⚠️ Gap — 待规划 |
| MEDIUM | K8s labs 缺 `experiment_background`、`completion_summary`、`ai_tutor_context` | NOTE — 内容遗留，可在下次 lab 迭代补充 |
| MEDIUM | K8s labs 步骤缺 `troubleshoot` 字段 | NOTE — 内容遗留 |
| LOW | Linux lab 6c439064 `experiment_background` 内容完整 | ✅ 已有 |
