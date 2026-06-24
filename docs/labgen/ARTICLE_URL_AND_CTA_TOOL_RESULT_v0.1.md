# Article URL + CTA Tool Result v0.1

**Date**: 2026-06-24
**Operator**: Claude Code acting as senior dev + ops
**Task**: G-58 — Article URL + CTA Tool Implementation
**No real secrets in this document.**

---

## A. Executive Summary

**Final Decision**: `ARTICLE_URL_AND_CTA_TOOL_READY`

| Question | Answer |
|----------|--------|
| article_url 字段已实现？ | ✅ YES — Optional, validated (http/https only, max 2000 chars) |
| CTA generation 已实现？ | ✅ YES — 4 formats: plain / markdown / html / copyable text |
| Admin-only boundary enforced？ | ✅ YES — require_admin_user on all admin endpoints |
| Learner exposure safe？ | ✅ YES — only exposed when cta_enabled=True; source_article_id never exposed |
| No public upload remains true？ | ✅ YES — zero new learner-facing write endpoints |
| No live LLM？ | ✅ YES — CTA generation is pure string building, zero external calls |

---

## B. North Star Alignment

| 检查项 | 状态 |
|--------|------|
| 读了能练，练了能绑定原文 | ✅ article_url → lab binding 已实现 |
| Admin-curated Article-to-Lab | ✅ 仅 admin 可设置 article metadata |
| Article CTA → Lab deep link | ✅ GET /api/labgen/drafts/{id}/cta 返回标准 CTA |
| Reader only practices, not generates | ✅ 无普通用户写入 article 或生成 lab 的路径 |
| No public upload | ✅ 无 public article upload API |
| No live LLM | ✅ 零 LLM 调用 |

---

## C. Implementation Summary

### C.1 Model Fields (`backend/labgen/models.py`)

Added to `LabDraft`:

| Field | Type | Default | Validator |
|-------|------|---------|-----------|
| `article_url` | `Optional[str]` | `None` | http/https only, max 2000 chars |
| `article_title` | `Optional[str]` | `None` | no `<` or `>`, max 500 chars |
| `article_channel` | `Optional[str]` | `None` | allowlist: official_site/wechat/zhihu/csdn/github/other |
| `article_published_at` | `Optional[datetime]` | `None` | standard Pydantic datetime |
| `cta_enabled` | `bool` | `False` | admin must explicitly set True |

All fields are Optional and backward-compatible — existing labs (including all 6 published) automatically have `None`/`False` defaults.

### C.2 API Endpoints

| Endpoint | Auth | Action |
|----------|------|--------|
| `PATCH /api/labgen/drafts/{id}` | admin | Now supports article metadata fields |
| `GET /api/labgen/drafts/{id}/cta` | admin | Returns 4 CTA format strings |
| `GET /api/labs/{id}` | learner | Returns article_url/title/channel when cta_enabled=True |

### C.3 CTA Format Outputs

**1. plain_cta** (any platform)
```
https://lab.cloudnetops.tech/labgen-lab.html?labId=<uuid>
```

**2. copyable_text** (WeChat / Zhihu body)
```
本文配套实操实验已上线，无需安装任何环境，在浏览器中直接练习：
点击进入实验 → <title>
https://lab.cloudnetops.tech/labgen-lab.html?labId=<uuid>
实验完成后环境自动销毁，数据不保留。
```

**3. markdown_cta** (GitHub / Blog)
```markdown
> **配套实验**：[<title>](https://lab.cloudnetops.tech/labgen-lab.html?labId=<uuid>)
> 无需本地环境，浏览器直接练习，完成后自动销毁。
```

**4. html_cta** (article.html embed)
```html
<div class="lab-cta-block"><p>本文配套实操实验已上线：</p><a href="/labgen-lab.html?labId=<uuid>" class="btn-start-lab"><title></a><small>无需安装环境，完成后自动销毁</small></div>
```

### C.4 Admin UI Changes (`frontend/labgen-admin.html`)

Extended from 110 to ~240 lines:
- Article Binding section: article_url input, article_title input, channel select, published_at date, cta_enabled checkbox, Save button
- CTA Copy section: 4 `<pre>` blocks with Copy buttons (uses `navigator.clipboard.writeText`)
- All outputs written via `.textContent` (no `innerHTML` of unsanitized data)
- Refresh CTA button to reload after metadata save

### C.5 Frontend Client (`frontend/js/labgenClient.js`)

Added 3 methods + 3 PATHS entries:
- `getDraft(labId)` — `GET /api/labgen/drafts/:lab_id`
- `patchDraft(labId, body)` — `PATCH /api/labgen/drafts/:lab_id`
- `getDraftCta(labId)` — `GET /api/labgen/drafts/:lab_id/cta`

### C.6 Audit Events

All article metadata changes flow through the existing `AdminReviewDiff` append-only audit log (via `_build_diff` in routes.py). Changes to `article_url`, `article_title`, `article_channel`, `cta_enabled` are recorded with old/new values.

### C.7 Validation Rules

| Field | Rule |
|-------|------|
| `article_url` | Must start with `http://` or `https://`; max 2000 chars; `javascript:` and `data:` schemes rejected |
| `article_title` | No `<` or `>` characters; max 500 chars |
| `article_channel` | Enum allowlist: `{official_site, wechat, zhihu, csdn, github, other}` |
| `cta_enabled` | Default False; admin must explicitly enable |

---

## D. Safety / Exposure Rules

| Rule | Status |
|------|--------|
| raw article text not exposed | ✅ No article text field in any API response |
| source_article_id not exposed to learner | ✅ Not in LearnerLabDetail or LearnerLabCatalogItem |
| source_article_id not exposed in CTA | ✅ Not in LabDraftCTAResponse |
| No URL scraping | ✅ article_url is storage only; _build_cta() makes zero HTTP calls |
| No live LLM | ✅ CTA is pure f-string generation |
| No ordinary user upload | ✅ All article metadata endpoints require admin |
| CTA wording constraints | ✅ CTA text expresses: lab is for this article, no local setup, auto-destroyed; does NOT claim: any article generates lab, user upload, live AI, public launch |
| draft/internal lab CTA not exposed to learners | ✅ GET /api/labs/{id} only returns article fields if cta_enabled=True AND publish_status=PUBLISHED |

---

## E. Test Results

| Category | Tests | Status |
|----------|-------|--------|
| Article metadata PATCH (admin) | 13 | ✅ PASS |
| CTA generation endpoint | 15 | ✅ PASS |
| Learner exposure rules | 5 | ✅ PASS |
| Regression (existing labs unaffected) | 6 | ✅ PASS |
| Learner field model structure | 3 | ✅ PASS |
| **New tests total** | **42** | ✅ PASS |
| **Full suite** | **4382+** | ✅ PASS |
| Coverage | — | 92.26% |
| 8 safety scans | — | ✅ PASS |
| safety-reviewer | — | APPROVED_WITH_NOTES → MEDIUM fixed |
| pre-commit | — | ✅ PASS |
| pre-push | — | ✅ PASS (run at commit) |

---

## F. Known Limitations

| Limitation | Notes |
|------------|-------|
| Email registration is P1 | Not implemented in this task; username+password registration remains |
| Article detail embedded CTA component | article.html does not auto-render CTA block from lab data; admin must copy from admin UI |
| No live LLM | Stub mode only; LLM generation is not enabled |
| No public upload | Phase 1 only: admin-curated article input |
| No customer pilot | Cohort expansion gate not passed |
| No public launch | Not applicable in current Phase 1 scope |

---

## G. Issue Triage

| Level | Issue | Status |
|-------|-------|--------|
| BLOCKER | — | None |
| HIGH | — | None |
| MEDIUM | `article_channel` had no validator in initial implementation | FIXED — enum allowlist added before commit |
| LOW | article.html does not auto-embed CTA component | NOTE — admin copies from admin UI; future work if needed |
| NOTE | K8s labs still missing experiment_background/completion_summary content | Pre-existing; not introduced by this task |

---

## H. Final Decision

```
ARTICLE_URL_AND_CTA_TOOL_READY
```

**Rationale**:

1. ✅ Article → Lab binding implemented (article_url + 4 metadata fields)
2. ✅ Admin CTA tool implemented (4 format outputs + 1-click copy in admin UI)
3. ✅ Learner exposure gated by cta_enabled flag
4. ✅ source_article_id never exposed to learner or CTA responses
5. ✅ All validators enforced server-side (not just client-side)
6. ✅ safety-reviewer MEDIUM gap fixed before commit
7. ✅ 42 new tests + full suite 92.26% coverage maintained
8. ✅ Existing 6 published labs backward-compatible (all new fields default None/False)

---

## I. Recommended Next Step

Three options (choose one):

| Option | Description |
|--------|-------------|
| **Admin Article Input MVP** | Wire a published Directus article to a published lab via article_url; manually test the full flow (admin sets URL + CTA → copies to article → learner clicks CTA → registers → starts lab → completes) |
| **Email Registration P1** | Add optional email field to user model + register form; store only, no email send |
| **Article Detail Embedded CTA Component** | Auto-render lab-cta-block in article.html when article has a bound lab with cta_enabled=True |
| **Hold Expansion** | No new features until admin does a dry-run of the complete Article → CTA → Reader flow with an existing published lab |

**Recommended**: Admin Article Input MVP — wire one existing published lab to one article, test the complete flow end-to-end, before expanding.

---

## J. Technical Self-Check

- ✅ No TODO/FIXME
- ✅ No placeholder-as-success
- ✅ No public upload
- ✅ No ordinary user article generation
- ✅ No live LLM
- ✅ No URL scraping
- ✅ No raw article text exposure
- ✅ No source_article_id learner exposure
- ✅ No unsafe CTA claim
- ✅ CTA does not claim any article generates lab
- ✅ CTA does not claim live AI enabled
- ✅ CTA does not claim public launch
- ✅ Non-admin cannot update article metadata
- ✅ Draft/internal lab CTA not exposed to learner
- ✅ K8s regression: 0 failures
- ✅ Linux regression: 0 failures
- ✅ Catalog regression: 0 failures
- ✅ Runtime behavior unchanged
- ✅ Production VMID 500-599 untouched
- ✅ No concurrency increase
- ✅ Email registration not implemented (remains P1)
- ✅ Docker domain not started
- ✅ No new lab published
- ✅ No cohort / customer pilot started
- ✅ No BLOCKER / HIGH / MEDIUM downgraded to NOTE

---

## K. Modified Files

| File | Change |
|------|--------|
| `backend/labgen/models.py` | Added 5 article binding fields + 3 validators to `LabDraft` |
| `backend/labgen/routes.py` | `PatchDraftRequest` + `LabDraftCTAResponse` + `GET /api/labgen/drafts/{id}/cta` |
| `backend/labgen/learner_catalog.py` | `LearnerLabDetail` + cta_enabled-gated exposure in `get_published_lab_detail` |
| `frontend/js/labgenClient.js` | `getDraft`, `patchDraft`, `getDraftCta` methods + PATHS |
| `frontend/labgen-admin.html` | Article metadata form + CTA copy section |
| `tests/test_labgen_article_url_cta.py` | 42 new tests (new file) |
| `docs/labgen/ARTICLE_URL_AND_CTA_TOOL_RESULT_v0.1.md` | This file |
| `docs/labgen/PHASE1_GAP_PRIORITIZATION_v0.1.md` | P0 gaps marked CLOSED |
| `deploy/labgen/staging_ops_ticket_status.md` | G-58 entry appended |
| `CHANGELOG.md` | [Unreleased] updated |
