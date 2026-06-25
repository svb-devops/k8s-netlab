# Real External Article Binding Gate & E2E Validation v0.1

**Date**: 2026-06-24
**Operator**: Claude Code — senior dev + ops
**Task ref**: G-63
**Status**: REAL_EXTERNAL_ARTICLE_BINDING_NEEDS_OWNER_INPUT

---

## A. Executive Summary

| 项目 | 结论 |
|------|------|
| Owner 是否提供真实外部文章 URL？ | **否** — 本次任务消息无 `real_article:` 输入块 |
| 真实外部文章绑定是否完成？ | **否** — 缺少 owner 输入，不得伪造 |
| mock_admin_article 限制是否关闭？ | **否** — 仍为 mock/platform-internal article |
| E2E validation 是否执行？ | **否** — 路径 B，无真实外部文章，不得执行 real E2E |
| 无 public upload 是否保持？ | **是** ✅ |
| 无 live LLM 是否保持？ | **是** ✅ |
| 无 URL scraping 是否保持？ | **是** ✅ |

**Owner Input Gate 结论**：本次消息中未包含 `real_article:` 输入块，无 `article_url`。
按照严格规则（路径 B），不得伪造真实外部文章 URL，不得将现有 platform-internal article 当作 real external article。
Final decision: **REAL_EXTERNAL_ARTICLE_BINDING_NEEDS_OWNER_INPUT**。

---

## B. North Star Alignment

| 原则 | 状态 |
|------|------|
| 读了能练，读完即绑 | ⏸ 待 owner 提供真实外部文章后完成闭环 |
| Admin-curated Article-to-Lab | ✅ 架构已就绪，等待真实文章输入 |
| 真实发布的文章 → lab CTA | ⏸ 当前文章为 platform-internal，非预先独立发布 |
| 读者只练习，不上传文章 | ✅ 保持 |
| 无 public upload | ✅ 保持 |
| 无 live LLM | ✅ 保持 |
| 无 URL scraping | ✅ 保持 |

---

## C. Owner Input

**必填字段**（全部为空/未提供）：

| 字段 | 提供状态 | 说明 |
|------|---------|------|
| `article_url` | ❌ **缺失** | 真实外部文章的完整 URL（http/https 开头） |
| `article_title` | ❌ **缺失** | 文章在外部平台上显示的标题 |
| `article_channel` | ❌ **缺失** | 发布渠道（见下方枚举） |
| `article_published_at` | ❌ **缺失** | 在外部平台的发布时间（ISO 8601 格式） |
| `target_lab_id` | ❌ **缺失** | 要绑定的 lab ID（推荐 `6c439064` — Linux Files and Permissions Basics） |
| `topic_match_confirmation` | ❌ **缺失** | 文章主题是否与 lab 匹配（yes/no） |

**有效的 `article_channel` 枚举值**：
```
official_site | wechat | zhihu | csdn | github | other
```

> ⚠️ 当前系统中 Linux 文章的 `article_url` 为 `https://lab.cloudnetops.tech/article.html?slug=linux-files-permissions-basics`，
> 这是平台自身的 article 页面（Directus 内部管理内容），**不是**预先在外部独立平台发布的文章。
> `article_type` 在系统中为 None（历史分类：`mock_admin_article`，非外部预发布）。
> 不得将此视为"真实外部文章绑定"。

---

## D. Binding Result

本次未执行绑定（缺少 owner 输入）。

| 项目 | 状态 |
|------|------|
| metadata 更新 | 未执行 |
| CTA 重新生成 | 未执行 |
| article.html embedded CTA 验证 | 未执行 |
| external platform CTA 处理 | 未执行 |
| mock 标记状态 | 仍为 platform-internal（mock_admin_article 历史分类） |

### 当前系统中的文章状态（参考）

```
draft id:        (lab 6c439064 的 draft)
article_url:     https://lab.cloudnetops.tech/article.html?slug=linux-files-permissions-basics
article_channel: official_site
article_title:   Linux 文件与权限基础：创建、查看并修改权限
article_type:    None (历史分类: mock_admin_article)
cta_enabled:     True
source_article_id: art-linux-files-permissions-001
```

此 URL 指向平台自身 article 页（Directus 管理），**不符合** real external article 要求。

---

## E. Reader E2E Result

未执行（缺少真实外部文章输入，不得伪造）。

---

## F. Safety / Exposure

已验证（基于现有代码，无代码变更）：

| 检查 | 状态 |
|------|------|
| raw article text 未暴露 | ✅ 确认（articles_routes.py content 字段不在 CTA 响应中）|
| source_article_id 未暴露 | ✅ 确认（ArticleLabCTAResponse 无此字段）|
| email 未暴露 | ✅ 确认（/api/auth/me / AuthResponse / catalog / lab API 均无 email）|
| password_hash 未暴露 | ✅ 确认 |
| 无 URL scraping | ✅ 零外部 HTTP 调用 |
| 无 live LLM | ✅ fake_only 模式 |
| 无 ordinary user upload | ✅ 无 public write 端点 |

---

## G. Negative Checks

已验证（readiness checks，路径 B）：

| 检查 | 状态 |
|------|------|
| docs 中无 mock 被声称为 real external article | ✅ PASS |
| 代码中无 `mock_admin_article` 字符串（作为 real） | ✅ PASS — 仅为历史文档分类标注 |
| docs 中的 zhihu/weixin URL 为注释示例，非声称的真实绑定 | ✅ PASS |
| 无伪造的外部文章 URL | ✅ PASS — 本次无 owner 输入，未伪造 |
| owner input template 已创建 | ✅ 见下方 Section K |
| pre-commit PASS | ✅（文档变更，无代码变更）|

---

## H. Known Limitations

- **Owner 未提供真实外部文章 URL** — 这是本次任务停止在 NEEDS_OWNER_INPUT 的唯一原因。
- 当前 Linux 文章系统存在于平台自身（Directus，`lab.cloudnetops.tech/article.html`），内容质量完整，但不是预先在外部独立平台发布的文章。
- `official_site` 渠道原则上有效（若 owner 确认平台自身文章即为"官方渠道"发布的真实文章），但必须由 owner 明确确认，Claude Code 不得自行认定。
- email verification 仍在 Phase 1 范围外。
- forgot password 仍在 Phase 1 范围外。
- 无 customer pilot。
- 无 public launch。
- 无并发提升。

---

## I. Issue Triage

| 级别 | 数量 | 说明 |
|------|------|------|
| BLOCKER | 0 | 无代码 BLOCKER |
| HIGH | 0 | |
| MEDIUM | 0 | |
| LOW | 0 | |
| NOTE | 1 | 当前 article_url 指向平台自身，非外部独立发布——需 owner 澄清或提供外部 URL |

---

## J. Final Decision

```
REAL_EXTERNAL_ARTICLE_BINDING_NEEDS_OWNER_INPUT
```

原因：
1. 本次任务消息中无 `real_article:` 输入块
2. 无 `article_url`（外部平台）由 owner 明确提供
3. 不得伪造，不得将 platform-internal article 声称为 real external article
4. 所有 readiness checks (path B) PASS
5. Owner input template 已创建（见 Section K）

---

## K. Owner Input Template

**请 owner 填写以下信息后，重新提交执行 Real External Article Binding：**

```
real_article:
  article_url: <完整 URL，http/https 开头，外部平台地址>
  article_title: <文章在外部平台显示的标题>
  article_channel: <official_site | wechat | zhihu | csdn | github | other>
  article_published_at: <发布时间，格式 YYYY-MM-DDTHH:MM:SSZ>
  target_lab_id: <要绑定的 lab ID，推荐 6c439064>
  topic_match_confirmation: <yes | no>
```

**填写说明**：

| 字段 | 说明 | 示例 |
|------|------|------|
| `article_url` | 文章在外部平台的完整访问地址 | `https://zhuanlan.zhihu.com/p/123456` 或 `https://lab.cloudnetops.tech/article.html?slug=linux-files-permissions-basics`（若确认以官方站点为发布渠道） |
| `article_title` | 文章在外部平台显示的标题，不含 HTML 标签 | `Linux 文件与权限基础：创建、查看并修改权限` |
| `article_channel` | 发布渠道枚举（official_site = 平台/官网） | `official_site` |
| `article_published_at` | 发布时间 | `2026-06-24T00:00:00Z` |
| `target_lab_id` | 推荐绑定 Linux lab | `6c439064` |
| `topic_match_confirmation` | 文章主题是否与 lab 匹配 | `yes` |

**特殊说明**：
若 owner 确认 `lab.cloudnetops.tech/article.html?slug=linux-files-permissions-basics` 即为官方渠道
（`article_channel: official_site`）的真实发布文章，则 article_url 可填该地址，并需在
`topic_match_confirmation: yes` 确认主题匹配。Claude Code 收到此确认后即可执行绑定。

---

## L. Recommended Next Step

```
Real External Article Binding Round 2
```

前提：Owner 填写 Section K 的 owner input template 并重新提交。

其他候选（若 owner 决定暂缓 article binding）：
- Small Cohort Planning Gate
- Email Verification / Password Recovery Planning
- Admin Article Input MVP Round 2
- Hold Expansion

---

## M. Technical Self-Check

| 检查项 | 状态 |
|--------|------|
| 无 TODO/FIXME | ✅ |
| 无 placeholder-as-success | ✅ |
| 无 fake real article URL | ✅ |
| 无 mock_admin_article 当 real external article | ✅ |
| 无 article-lab mismatch | ✅（未绑定，不存在 mismatch）|
| 无 CTA 指向错误 lab | ✅ |
| 无 source_article_id learner exposure | ✅ |
| 无 raw article text exposure | ✅ |
| 无 email exposure | ✅ |
| 无 password_hash exposure | ✅ |
| 无 public upload | ✅ |
| 无 ordinary user article generation | ✅ |
| 无 live LLM | ✅ |
| 无 URL scraping | ✅ |
| 无 unsafe CTA claim | ✅ |
| 无 article.html CTA regression | ✅（现有 CTA 逻辑未变更）|
| 无 registration redirect regression | ✅ |
| 无 K8s regression | ✅ |
| 无 Linux regression | ✅ |
| 无 catalog regression | ✅ |
| 无 runtime behavior unintended change | ✅（无代码变更）|
| 无 production VMID 500-599 touch | ✅ |
| 无并发提升 | ✅ |
| Docker domain 未启动 | ✅ |
| 未发布新 lab | ✅ |
| 未启动 cohort/customer pilot | ✅ |
| 未接入邮件发送服务 | ✅ |
| 未新增 SMTP / SendGrid / SES secrets | ✅ |
| 无 BLOCKER/HIGH 被降级为 NOTE | ✅ |

---

## N. Modified Files

| 文件 | 变更 |
|------|------|
| `docs/labgen/REAL_EXTERNAL_ARTICLE_BINDING_RESULT_v0.1.md` | 本文件（新增）|
| `deploy/labgen/staging_ops_ticket_status.md` | G-63 条目追加 |
| `CHANGELOG.md` | [Unreleased] 更新 |

---

*Artifact created: 2026-06-24. No code changes. Path B executed.*
