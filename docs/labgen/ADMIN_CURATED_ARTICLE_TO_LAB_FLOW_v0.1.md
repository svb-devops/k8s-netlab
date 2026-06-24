# Admin-Curated Article-to-Lab Flow v0.1

**Date**: 2026-06-24
**Operator**: Claude Code acting as senior dev + ops
**Status**: Phase 1 Authoritative — supersedes any prior language implying open user upload
**No real secrets in this document.**

---

## A. Phase 1 One-Sentence Definition

> v0.1 阶段：LabGen 只支持管理员提供文章或技术主题，系统生成可审核的实验草稿，管理员审核发布后，在外部平台（微信/知乎/CSDN/GitHub）和网站首页同步发布带 CTA 链接的文章，普通读者仅从已发布文章的 CTA 进入对应实验学习，不上传文章，不生成实验，不发布实验。

---

## B. Standard Authoring Flow

```
Admin selects article/topic
  ↓
[Article Operability Check]
  - Does the article describe reproducible commands?
  - Is the content self-contained for an isolated sandbox?
  - Does the admin hold rights / consent to use this content?
  ↓
POST /api/labgen/article-drafts
  (raw_text input, Stub mode, zero LLM calls)
  ↓
[Draft Guided Practice Lab generated]
  ↓
Admin reviews Draft in labgen-admin.html
  - Edit step content (why / do / commands / observe / explain)
  - Verify each step's verification spec
  - Set article_url (external article link) ← P0 Gap: not yet supported
  ↓
POST /api/labgen/drafts/{id}/validate
  (StaticValidator: 13-point publish gate)
  ↓
[Internal Rehearsal]
  (rehearsal_required=true → rehearsal_completed=true required before publish)
  ↓
POST /api/labgen/drafts/{id}/publish
  ↓
[Lab published: visible in /api/labs catalog]
  ↓
Admin publishes article to external platforms + website homepage
  - 外部平台：微信公众号、知乎、CSDN、GitHub
  - 网站首页：landing.html（Directus CMS 管理，设为 published 即上线）
  - 文章中嵌入 CTA 链接（deep link → /labgen-lab.html?labId=<uuid>）← P0 Gap: 无标准工具
  ↓
Reader sees article (external platform or homepage)
  ↓
Reader clicks CTA link
  ↓
[Reader registers / logs in]
  - 当前：用户名 + 密码注册
  - P1 Gap：无邮箱字段
  ↓
POST /api/lab-sessions
  (6-point precheck: quota / ownership / taint / domain flags)
  ↓
Reader performs steps in browser terminal
  ↓
POST /api/lab-sessions/{id}/steps/{step_id}/check
  (auto-verify: K8s API / Linux command output)
  ↓
POST /api/lab-sessions/{id}/complete
  ↓
[Cleanup: namespace deleted / sandbox removed / credentials revoked]
  Lab session → LAB_CLOSED
```

---

## C. What Phase 1 Does NOT Allow

The following are explicitly out of scope for v0.1. Any document, PR, or system design that includes these items violates the Phase 1 boundary and must be rejected:

| Prohibited Item | Reason |
|-----------------|--------|
| 普通用户上传文章 | Phase 2+ only; requires rights confirmation, content safety, operability classification |
| UGC（用户生成内容） | Requires moderation pipeline not yet built |
| 任意文章自动生成实验 | Reliability not validated; would misrepresent platform capability |
| Live LLM pipeline | Not enabled; system runs in `fake_only` mode |
| URL scraping | Legal and content quality concerns |
| Auto-publishing generated drafts | Admin review gate is mandatory |
| Public launch | No public rollout until further milestone |
| Customer pilot | Blocked (NO_SUITABLE_SMALL_CUSTOMER) |
| Docker domain | Not in scope |
| 新增 domain expansion | Only K8s + Linux validated |
| Concurrency increase | No performance work this phase |
| 触碰 production VMID 500-599 | Reserved for K8s learner VMs only |

---

## D. Reader Boundary

### What readers CAN do

- Read articles on external platforms or the website homepage (`landing.html`)
- Click article CTA link → enter corresponding lab
- Register / log in (username + password; email P1)
- Start a lab session (`POST /api/lab-sessions`)
- Execute commands in the browser terminal
- Check step progress (`POST /api/lab-sessions/{id}/steps/{step_id}/check`)
- Complete the lab (`POST /api/lab-sessions/{id}/complete`)
- Submit feedback

### What readers CANNOT do

- Upload articles to generate labs
- Modify lab templates or step content
- Publish or draft labs
- Access admin routes (`/api/labgen/drafts`, `/api/labgen/article-drafts`)
- Access internal routes (`/internal/*`)
- Bypass sandbox isolation (no access to host OS, Proxmox API, or other VMs)
- View `source_article_id` (internal ID, never exposed to learner API)
- View raw article text (only article CTA metadata visible)

---

## E. Admin Boundary

### What admins are responsible for

- 提供文章原文或技术主题（作为输入）
- 确认文章可行性（命令可复现、内容自洽）
- 确认内容权限（转载或原创）
- 审核实验草稿（步骤完整性、验证规格、安全性）
- 内部排练（rehearsal_completed=true）
- 发布实验（publish lab after all gates pass）
- 在外部平台发布文章（附 CTA 链接）
- 在 Directus 后台发布文章至网站首页
- 管理 CTA 链接（deep link 与 lab 的绑定）

### What admins CANNOT do (system constraints)

- 绕过 StaticValidator 门控直接发布
- 在 rehearsal_completed=false 时发布
- 在 `publish_blocked` 状态下强制发布

---

## F. Article-Lab Binding (Current Limitation)

As of v0.1, the article-lab binding has the following limitations:

| Capability | Status |
|------------|--------|
| `source_article_id` stored in LabDraft | ✅ Exists |
| External article URL stored in LabDraft | ❌ P0 Gap — `article_url` field missing |
| CTA deep link format defined | ✅ `/labgen-lab.html?labId=<uuid>` |
| CTA copy tool in admin UI | ❌ P0 Gap — no standard tool |
| Admin can set `article_url` via PATCH | ❌ P0 Gap — PATCH endpoint does not support it |
| Reader sees "back to article" link | ❌ Blocked by `article_url` gap |
| Reader sees article CTA on lab completion | ❌ Blocked by `article_url` gap |

These gaps are tracked in [PHASE1_GAP_PRIORITIZATION_v0.1.md](PHASE1_GAP_PRIORITIZATION_v0.1.md).

---

## G. Homepage Article System

The website homepage (`https://lab.cloudnetops.tech/`) already has a functioning article publication system:

| Component | Implementation |
|-----------|---------------|
| Public homepage | `frontend/landing.html` — article list, no login required |
| Article detail page | `frontend/article.html` — body + comments |
| Articles API | `GET /api/articles` (Directus CMS, published filter) |
| Article management | Directus admin at `127.0.0.1:8055` — set `status=published` to go live |
| Reader comments | `POST /api/articles/{slug}/comments` (requires login) |

**Sync workflow**: Admin writes article in Directus → sets `status=published` → article appears on homepage automatically. No code deploy required.

**Gap**: The article detail page (`article.html`) does not yet have a standard CTA block linking to the corresponding lab. This is tracked as P0 Gap 2 in [PHASE1_GAP_PRIORITIZATION_v0.1.md](PHASE1_GAP_PRIORITIZATION_v0.1.md).

---

## H. Domain Coverage

| Domain | Published Labs | Verified Learner Path | Status |
|--------|---------------|----------------------|--------|
| K8s (kubectl) | 5 labs | ✅ Real learner PASSED (G-34) | Production-ready for K8s labs |
| Linux (sandbox) | 1 lab | ✅ Trusted reader PASSED (G-51) | Feature-flagged (single lab) |
| Docker | 0 labs | ❌ Not in scope | Phase 1 forbidden |

Both K8s and Linux lab structures serve as canonical templates for new labs. See [EXISTING_LAB_TEMPLATE_EXTRACTION_v0.1.md](EXISTING_LAB_TEMPLATE_EXTRACTION_v0.1.md).
