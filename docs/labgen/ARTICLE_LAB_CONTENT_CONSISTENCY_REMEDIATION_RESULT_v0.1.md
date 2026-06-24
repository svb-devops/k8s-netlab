# Article-Lab Content Consistency Remediation Result v0.1

**Date**: 2026-06-24
**Operator**: Claude Code acting as senior dev + ops
**Task**: G-60 — Article-Lab Content Consistency Remediation v0.1
**No real secrets in this document.**

---

## A. Executive Summary

**Final Decision**: `ARTICLE_LAB_CONTENT_CONSISTENCY_REMEDIATED_WITH_NOTES`

| 检查项 | 状态 |
|--------|------|
| Article-lab topic mismatch fixed? | ✅ YES — K8s welcome article unbound; Linux article created and bound |
| Step 3 chmod mismatch fixed? | ✅ N/A — G-59 result doc was incorrect; data already consistent |
| Consistency gate added? | ✅ YES — rule-based keyword check in topic_consistency.py |
| CTA regenerated with correct article? | ✅ YES — topic_consistency_warning=None |
| Reader E2E revalidation passed? | ✅ YES — session 3254de61, LAB_CLOSED, cleanup_verified=True, residual=0 |
| source_article_id not exposed? | ✅ YES |
| raw article text not exposed? | ✅ YES |
| No public upload? | ✅ YES |
| No live LLM? | ✅ YES |
| No URL scraping? | ✅ YES |
| BLOCKER/HIGH/MEDIUM? | ✅ NONE |

WITH_NOTES reason: Article used is `mock_admin_article` (created for this validation task, not a pre-existing externally published article).

---

## B. North Star Alignment

| 检查项 | 状态 |
|--------|------|
| 读了能练，练了能绑定原文 | ✅ article_url → lab binding 持久化；文章主题与实验一致 |
| Article must match lab | ✅ Linux article ("文件与权限基础") → Linux lab (chmod/stat/permissions) |
| Guided Practice Lab must not contradict verifier | ✅ Step 3: do/commands/observe/verifier 全部 chmod 600 |
| Admin-curated, not user-uploaded | ✅ 仅 admin PATCH；普通用户 403 |
| No live LLM | ✅ topic_consistency check = pure keyword matching |
| No URL scraping | ✅ _build_cta() 零 HTTP 调用 |

---

## C. Issue Details

### Issue 1: Article-Lab Topic Mismatch (FIXED)

**Original state**: Linux lab `6c439064` (Linux Files and Permissions Basics) was bound to article `welcome-to-k8s-netlab` (K8s NetLab platform introduction article).

| Field | Before | After |
|-------|--------|-------|
| `article_url` | `https://lab.cloudnetops.tech/article.html?slug=welcome-to-k8s-netlab` | `https://lab.cloudnetops.tech/article.html?slug=linux-files-permissions-basics` |
| `article_title` | 欢迎来到 K8S NetLab | Linux 文件与权限基础：创建、查看并修改权限 |
| `article_channel` | official_site | official_site |
| `cta_enabled` | true | true |

**Severity**: MEDIUM — A reader following a K8s platform intro article would be routed to a Linux permissions lab, causing topic confusion.

**Why not safe to proceed to embedded CTA before fixing**: If embedded CTA were deployed with the mismatched article, any reader viewing `welcome-to-k8s-netlab` would see a "Linux 文件与权限基础" lab CTA — semantically wrong and confusing.

### Issue 2: Step 3 chmod "Mismatch" (G-59 result doc error)

**Finding**: The G-59 result document incorrectly stated "step DO instruction says chmod 644 but verify expects 600". Inspection of actual `data/lab_drafts.json` shows:

| Field | Value |
|-------|-------|
| `commands` | `['chmod 600 demo/message.txt', 'stat -c "%a" demo/message.txt']` |
| `do` | "Change the permissions of demo/message.txt to **600** using chmod..." |
| `observe` | "stat outputs '**600**', confirming..." |
| `troubleshoot` | "...re-run chmod **600** demo/message.txt..." |
| `verifier expected_mode` | `600` |
| `explain.observation` | "If stat shows a different number (e.g. 644), re-run chmod **600**." — 644 is mentioned as an example of a WRONG result, not the correct command |

All fields say `chmod 600`. The G-59 documentation was incorrect. No code or data change required.

Regression tests added (Section F) to prevent future divergence.

---

## D. Fix Summary

### 1. Linux Article Created in Directus
- **Directus ID**: 3
- **Slug**: `linux-files-permissions-basics`
- **Title**: Linux 文件与权限基础：创建、查看并修改权限
- **Status**: published
- **Content**: Admin-curated article covering mkdir, echo, cat, chmod 600, stat; explains 600 vs 644 vs 755; includes lab CTA context
- **article_type**: `mock_admin_article` — created for this validation task; not a pre-existing externally published article

### 2. Article Binding Updated
Updated via `PATCH /api/labgen/drafts/6c439064-4cad-4229-addb-36927128d565` (admin cookie auth):
- `article_url`: `https://lab.cloudnetops.tech/article.html?slug=linux-files-permissions-basics`
- `article_title`: Linux 文件与权限基础：创建、查看并修改权限
- `article_channel`: official_site
- `cta_enabled`: true

Persistence confirmed: JSON file updated, GET returns same values.

### 3. Topic Consistency Gate Added

**New module**: `backend/labgen/topic_consistency.py`

```python
def check_article_lab_consistency(
    target_domain: Optional[str],
    article_title: Optional[str],
    article_url: Optional[str],
) -> Optional[str]:
```

- Rule-based keyword matching (zero LLM)
- Linux keywords: linux, 文件, 权限, chmod, shell, bash, terminal, 命令行, 目录, permission, file
- K8s keywords: kubernetes, k8s, pod, deployment, configmap, secret, service, ingress, namespace, helm, 容器, 集群, 部署
- Returns warning string on mismatch, None on match or no article bound
- Case-insensitive

**Integrated into**:
- `LabDraftCTAResponse`: new `topic_consistency_warning: Optional[str]` field
- `StaticValidator._validate_k8s()` and `_validate_linux()`: new check `content.article_lab_topic_consistency` (BlockingLevel.DRAFT_WARNING — not publish_blocking)

### 4. CTA Regenerated

`GET /api/labgen/drafts/6c439064/cta` after update:
- `topic_consistency_warning`: None ✅
- `plain_cta`: `https://lab.cloudnetops.tech/labgen-lab.html?labId=6c439064-4cad-4229-addb-36927128d565`
- `article_title`: Linux 文件与权限基础：创建、查看并修改权限
- `is_published`: true
- `cta_enabled`: true

---

## E. E2E Revalidation

**Reader account**: `g60-reader-01` (operator-controlled)

| Stage | Result |
|-------|--------|
| Registration | ✅ `POST /api/auth/register` → success |
| Login | ✅ session cookie issued |
| Lab detail (CTA target) | ✅ article_url=linux-files-permissions-basics, source_article_id absent |
| Start session | ✅ session_id=`3254de61-1e92-4f4a-bdf3-4a8ab7d84338`, LAB_ACTIVE |
| Step 1 | ✅ lfp-s1-v1 dir_exists, lfp-s1-v2 file_exists, lfp-s1-v3 content_matches — PASS |
| Step 2 | ✅ lfp-s2-v1 content_matches — PASS |
| Step 3 | ✅ chmod 600 applied; lfp-s3-v1 mode_matches(600) — PASS |
| Step 4 | ✅ no verify templates, auto-pass, ready_to_complete=True |
| Complete | ✅ LAB_CLOSED, cleanup_verified=True |
| Workspace after cleanup | ✅ DELETED |
| Active sessions | ✅ 0 |
| Tainted VMs | ✅ {} |

---

## F. Negative Checks

| Check | Result |
|-------|--------|
| Non-admin PATCH article metadata | ✅ HTTP 403 |
| Non-admin GET CTA endpoint | ✅ HTTP 403 |
| Invalid URL `javascript:alert(1)` | ✅ HTTP 422 |
| source_article_id absent in learner API | ✅ ABSENT |
| raw_text absent in learner API | ✅ ABSENT |
| K8s article to Linux lab → topic_consistency_warning fires | ✅ confirmed (unit tests) |
| Step 3 commands contain no 644 | ✅ confirmed |
| Step 3 do field contains no 644 | ✅ confirmed |
| Verifier expects 600, not 644 | ✅ confirmed |
| K8s Lab 5 in catalog unaffected | ✅ found (K8s lab present) |
| Linux runtime unaffected | ✅ 4 steps pass as before |
| CTA: no unsafe claim | ✅ clean wording |

---

## G. Known Limitations

| Limitation | Notes |
|------------|-------|
| `article_type = mock_admin_article` | The Linux article (`linux-files-permissions-basics`) was created in Directus specifically for this validation task. It is a real, published, platform-managed article with correct content — but it was not an independently pre-existing externally published piece. A purpose-authored article published first, then bound, would be the ideal flow. |
| article-topic gate is rule-based only | Keyword matching cannot understand semantics. An article titled "Deploy Linux apps with Kubernetes" would match both domains. This is acceptable for Phase 1 given the admin-curated constraint. |
| Embedded CTA not yet implemented | article.html does not auto-render lab-cta-block. Admin copies CTA from admin UI. This is the next recommended step. |
| Email registration remains P1 | Username+password only. Not implemented in this task. |
| No live LLM | Stub mode only. |
| No customer pilot | Phase 1 operator-controlled only. |

---

## H. Issue Triage

| Level | Issue | Status |
|-------|-------|--------|
| BLOCKER | — | None |
| HIGH | — | None |
| MEDIUM | — | None |
| LOW | Embedded CTA not in article.html | NOTE — next step |
| NOTE | Article is mock_admin_article | DOCUMENTED — content is real, creation timing is the note |
| NOTE | G-59 result doc incorrect about step 3 chmod | CORRECTED — data is and was already consistent |

---

## I. Final Decision

```
ARTICLE_LAB_CONTENT_CONSISTENCY_REMEDIATED_WITH_NOTES
```

**Rationale**:
1. ✅ Article-lab topic mismatch FIXED: Linux article created and bound to Linux lab
2. ✅ Step 3 chmod: already internally consistent (G-59 result doc was wrong — no code change needed)
3. ✅ Topic consistency gate added: rule-based keyword check, integrated into CTA and StaticValidator
4. ✅ CTA regenerated: topic_consistency_warning=None, all 4 formats correct
5. ✅ Reader E2E revalidation: LAB_CLOSED, cleanup_verified=True, residual=0
6. ✅ 12 negative checks passed
7. ✅ 4418 tests, 92.28% coverage, +33 new tests
8. ✅ source_article_id never exposed; no public upload; no live LLM; no URL scraping
9. WITH_NOTES: article is `mock_admin_article` (not pre-existing externally published)

---

## J. Recommended Next Step

| Option | Description |
|--------|-------------|
| **Article Detail Embedded CTA Component** (Recommended) | Auto-render lab-cta-block in article.html when article has a bound lab (cta_enabled=True). Now that article-lab topic consistency is fixed, this is safe to implement without routing confusion. |
| Admin Article Input MVP Round 2 | Author an externally published Linux article (on zhihu/csdn/official blog), bind it, repeat E2E — upgrades mock_admin_article to a real external article |
| Email Registration P1 | Add optional email field to register form |
| Small Cohort Planning Gate | Define cohort size and rollout plan (blocked until embedded CTA is deployed) |
| Hold Expansion | Freeze features; deploy existing Linux article + CTA to production page |

**Recommended**: Article Detail Embedded CTA Component — now unblocked by this consistency remediation.

---

## K. Technical Self-Check

- ✅ No TODO/FIXME in new code
- ✅ No placeholder-as-success
- ✅ No article-lab domain mismatch (FIXED)
- ✅ No Step command/verifier mismatch (was already correct)
- ✅ No CTA pointing to wrong topic
- ✅ No public upload
- ✅ No ordinary user article generation
- ✅ No live LLM
- ✅ No URL scraping
- ✅ No raw article text exposure
- ✅ No source_article_id learner exposure
- ✅ No unsafe CTA claim
- ✅ Non-admin cannot update article metadata (403)
- ✅ Non-admin cannot access CTA endpoint (403)
- ✅ Draft/internal lab CTA not startable by learner
- ✅ Email registration not implemented (remains P1)
- ✅ Docker domain not started
- ✅ No new lab published
- ✅ No cohort/customer pilot started
- ✅ No BLOCKER/HIGH/MEDIUM downgraded to NOTE
- ✅ K8s regression: 0 failures (4418 tests PASS)
- ✅ Linux regression: 0 failures
- ✅ Catalog regression: 0 failures
- ✅ Runtime behavior unchanged
- ✅ Production VMID 500-599 untouched
- ✅ No concurrency increase

---

## L. Modified Files

| File | Change |
|------|--------|
| `backend/labgen/topic_consistency.py` | New — rule-based article-lab consistency checker |
| `backend/labgen/routes.py` | Added `topic_consistency_warning` to `LabDraftCTAResponse`; call `_build_cta()` with warning |
| `backend/labgen/static_validator.py` | Added `_check_article_lab_topic_consistency()` to both K8s and Linux validation paths |
| `tests/test_labgen_article_lab_consistency.py` | New — 33 tests (A-E sections) |
| `docs/labgen/ARTICLE_LAB_CONTENT_CONSISTENCY_REMEDIATION_RESULT_v0.1.md` | This file (new) |
| `CHANGELOG.md` | [Unreleased] updated |
| `deploy/labgen/staging_ops_ticket_status.md` | G-60 entry (to be updated) |
| `data/lab_drafts.json` | article_url + article_title updated to Linux article (gitignored, live data) |
| Directus DB | Article id=3 (linux-files-permissions-basics) created |
