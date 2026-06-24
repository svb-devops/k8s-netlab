# Article Detail Embedded CTA Component Result v0.1

**Date**: 2026-06-24
**Operator**: Claude Code acting as senior dev + ops
**Task**: G-61 — Article Detail Embedded CTA Component v0.1
**No real secrets in this document.**

---

## A. Executive Summary

**Final Decision**: `ARTICLE_DETAIL_EMBEDDED_CTA_READY_WITH_NOTES`

| 检查项 | 状态 |
|--------|------|
| article.html 自动渲染 CTA block？ | ✅ YES — `loadLabCTA()` 在文章加载后自动调用 |
| 新增 reader-safe API 端点？ | ✅ YES — `GET /api/articles/{slug}/lab-cta`（无需认证） |
| CTA 使用已验证的 lab deep link？ | ✅ YES — `_validateCtaUrl()` 强制 `/labgen-lab.html?labId=` 前缀 |
| source_article_id 不暴露？ | ✅ YES |
| raw article text 不暴露？ | ✅ YES |
| admin notes 不暴露？ | ✅ YES |
| draft/internal lab 不暴露？ | ✅ YES — 仅 PUBLISHED + cta_enabled |
| 无 XSS 风险？ | ✅ YES — 全 DOM API，零 innerHTML 注入 |
| 无 public upload？ | ✅ YES |
| 无 live LLM？ | ✅ YES |
| tests | ✅ 43 新测试，4461 PASS，92.28% coverage |
| safety-reviewer | ✅ APPROVED_WITH_NOTES |
| production smoke | ✅ linux-files-permissions-basics → has_cta:true，cta_url 正确 |

WITH_NOTES 原因：Linux 文章（`linux-files-permissions-basics`）仍为 `mock_admin_article`（非外部预发布文章）。

---

## B. North Star Alignment

| 检查项 | 状态 |
|--------|------|
| 读了能练，练了能绑定原文 | ✅ article.html 自动显示配套实验入口，点击直达 lab |
| Admin-curated Article-to-Lab | ✅ CTA 仅在 admin 设置 cta_enabled=True 后出现 |
| article detail → lab CTA | ✅ 已实现 — article.html 展示 CTA block |
| reader only practices, not generates | ✅ 读者无法上传文章、生成实验 |
| no public upload | ✅ 零新增 public write 端点 |
| no live LLM | ✅ 零 LLM 调用 |
| no URL scraping | ✅ _build_cta() 零 HTTP 调用 |

---

## C. Implementation Summary

### 1. 新 API 端点

**`GET /api/articles/{slug}/lab-cta`** — reader-safe，无需认证

```python
class ArticleLabCTAResponse(BaseModel):
    has_cta: bool
    lab_id: Optional[str] = None
    lab_title: Optional[str] = None
    lab_summary: Optional[str] = None
    difficulty: Optional[str] = None
    estimated_duration: Optional[int] = None
    domain: Optional[str] = None
    cta_url: Optional[str] = None    # 始终为相对路径，从不为绝对 URL
    cta_text: str = "进入实验"
    sandbox_note: str = "实验运行在临时隔离环境中，完成后自动销毁。"
    cleanup_note: str = "完成实验后环境自动清理，数据不保留。"
```

- 匹配逻辑：解析 `article_url` 的 `slug` query 参数，精确匹配传入的 `{slug}`
- 过滤条件：`publish_status == PUBLISHED` AND `cta_enabled == True`
- 失败时返回 `has_cta=False`（非 404）— 对 reader 无感
- `lab_title` 和 `lab_summary` 经过 `sanitize_text()` 清洗

### 2. article.html

添加一个空 div 作为 CTA 槽位（位于文章内容与评论区之间）：

```html
<!-- Lab CTA block (rendered by article.js when linked lab exists) -->
<div id="lab-cta-container"></div>
```

### 3. article.js

新增三个函数：

**`loadLabCTA()`**
- 文章加载后自动调用
- fetch `/api/articles/{slug}/lab-cta`
- has_cta=False 时静默不渲染
- 所有异常都 catch 并静默（不影响 reader）

**`_validateCtaUrl(raw)`**
- 仅允许 `/labgen-lab.html?labId=` 前缀
- 拒绝 `javascript:`、`data:`、外部 URL、空值
- 失败时 `renderLabCTA` 直接返回，不渲染

**`renderLabCTA(container, data)`**
- 全程使用 `document.createElement()` + `.textContent`
- 零 `innerHTML` 注入动态内容
- 动态内容：lab_title、domain、estimated_duration、sandbox_note — 全部用 textContent
- 登录用户：`btn.href = ctaUrl`（已验证的相对路径）
- 未登录用户：`btn.href = '/login.html'`（静态安全 URL）

### 4. CTA block 外观

```
┌──────────────────────────────────────────────────────────┐
│ [配套实验]  读完这篇，可以立即动手实践                        │
│                                                          │
│ Linux Files and Permissions Basics                       │
│ 无需安装本地环境，在浏览器中直接操练，完成后自动销毁。           │
│                                                          │
│ [LINUX] 约 20 分钟                                        │
│                                                          │
│ [进入实验]                                                │
│                                                          │
│ 实验运行在临时隔离环境中，完成后自动销毁。                     │
└──────────────────────────────────────────────────────────┘
```

---

## D. Safety / Exposure

| 规则 | 状态 |
|------|------|
| raw article text 不暴露 | ✅ |
| source_article_id 不暴露 | ✅ 不在 ArticleLabCTAResponse 字段中 |
| article_url 不暴露 | ✅ 内部字段，不在响应中 |
| admin notes 不暴露 | ✅ |
| draft/internal lab 不暴露 | ✅ 仅 PUBLISHED+cta_enabled |
| 无 URL scraping | ✅ 零 HTTP 外部调用 |
| 无 live LLM | ✅ |
| 无 public write 端点 | ✅ GET only |
| cta_url 不为绝对 URL | ✅ `/labgen-lab.html?labId=...` 前缀验证 |
| XSS: textContent 而非 innerHTML | ✅ 全 DOM API |

---

## E. Test Results

| 类别 | 数量 | 结果 |
|------|------|------|
| A. API 端点测试 | 13 | ✅ PASS |
| B. `_find_lab_by_article_slug()` 单元测试 | 7 | ✅ PASS |
| C. `_validateCtaUrl()` 安全测试 | 8 | ✅ PASS |
| D. HTML/JS 静态安全测试 | 8 | ✅ PASS |
| E. 暴露规则测试 | 4 | ✅ PASS |
| F. 回归测试 | 3 | ✅ PASS |
| **合计** | **43** | **PASS** |
| 全量 | 4461 | PASS |
| 覆盖率 | 92.28% | ≥ 90% ✅ |
| bandit | — | PASS（同前） |
| safety-reviewer | — | APPROVED_WITH_NOTES |

---

## F. Production Smoke

| 检查 | 结果 |
|------|------|
| `GET /api/articles/linux-files-permissions-basics/lab-cta` | ✅ `has_cta:true`, lab_id=6c439064, cta_url=/labgen-lab.html?labId=6c439064... |
| `GET /api/articles/welcome-to-k8s-netlab/lab-cta` | ✅ `has_cta:false`（无绑定 lab） |
| `GET /api/articles/nonexistent-slug/lab-cta` | ✅ `has_cta:false` |
| forbidden fields in response | ✅ PASS（source_article_id/article_url/kubeconfig/password 全不在响应中） |
| service health post-restart | ✅ `{"status":"healthy","proxmox":{"connected":true}}` |
| error logs post-restart | ✅ 无新增异常 |

---

## G. Known Limitations

| Limitation | Notes |
|------------|-------|
| Linux 文章是 mock_admin_article | `linux-files-permissions-basics` 是为验证任务创建的，非外部预发布文章 |
| only one primary lab per article | 当前模型：一篇文章最多匹配一个 lab（第一个 PUBLISHED+cta_enabled 的命中） |
| email registration remains P1 | 未实现，用户名+密码 only |
| no customer pilot | Phase 1 operator-controlled only |
| no live LLM | Stub 模式 only |

---

## H. Issue Triage

| Level | Issue | Status |
|-------|-------|--------|
| BLOCKER | — | None |
| HIGH | — | None |
| MEDIUM | — | None |
| LOW | `_validateCtaUrl` 测试用 Python 重实现，与 JS 实现独立 | NOTE — 静态字符串扫描补偿（test_article_js_validates_cta_url_before_use 验证前缀字符串存在） |
| NOTE | Linux 文章是 mock_admin_article | DOCUMENTED |

---

## I. Final Decision

```
ARTICLE_DETAIL_EMBEDDED_CTA_READY_WITH_NOTES
```

**Rationale**:
1. ✅ `GET /api/articles/{slug}/lab-cta` 端点实现并通过测试
2. ✅ article.html + article.js 自动渲染 CTA block
3. ✅ 全 DOM API，零 innerHTML 注入
4. ✅ cta_url 验证器拒绝非 lab 路径
5. ✅ source_article_id / raw text / admin fields 从未暴露
6. ✅ draft/internal lab 从未暴露
7. ✅ production smoke: linux article → CTA 返回正确，k8s article → has_cta:false
8. ✅ 43 新测试，4461 tests PASS，92.28% coverage
9. ✅ safety-reviewer APPROVED_WITH_NOTES（无 BLOCKER/HIGH/MEDIUM）
10. WITH_NOTES: Linux 文章为 mock_admin_article

---

## J. Recommended Next Step

| Option | Description |
|--------|-------------|
| **Email Registration P1** (Recommended) | 注册表单加可选邮箱字段，存储即可，不发邮件 |
| Small Cohort Planning Gate | 定义 cohort 规模和 rollout 计划（现在 embedded CTA 已完成，技术路径畅通） |
| Real External Article Binding | 在外部平台（知乎/CSDN/微信）发布真正的 Linux 文章，再绑定到 lab，升级 mock_admin_article |
| Admin Article Input MVP Round 2 | 发布外部 Linux 文章，重跑 E2E |
| Hold Expansion | 冻结新功能；聚焦在当前 linux-files-permissions-basics 页面上的 CTA 体验 |

**Recommended**: Email Registration P1 — 现在 Article→Lab CTA 完整闭环已实现，reader 端完整体验只差登录注册体验的打磨。

---

## K. Technical Self-Check

- ✅ No TODO/FIXME in new code
- ✅ No placeholder-as-success
- ✅ No article-lab domain mismatch
- ✅ No CTA pointing to wrong lab
- ✅ No draft/internal lab exposure
- ✅ No cta_enabled=false exposure
- ✅ No source_article_id learner exposure
- ✅ No raw article text exposure
- ✅ No admin notes exposure
- ✅ No unsafe innerHTML with untrusted content
- ✅ No XSS risk from title/summary/domain/sandbox_note
- ✅ No public upload
- ✅ No ordinary user article generation
- ✅ No live LLM
- ✅ No URL scraping
- ✅ No registration/email scope creep
- ✅ K8s regression: 0 failures (4461 tests PASS)
- ✅ Linux regression: 0 failures
- ✅ Catalog regression: 0 failures
- ✅ Runtime behavior unchanged
- ✅ Production VMID 500-599 untouched
- ✅ No concurrency increase
- ✅ Docker domain not started
- ✅ No new lab published
- ✅ No cohort/customer pilot started
- ✅ No BLOCKER/HIGH/MEDIUM downgraded to NOTE

---

## L. Modified Files

| File | Change |
|------|--------|
| `backend/articles_routes.py` | 新增 `ArticleLabCTAResponse`、`get_lab_draft_repository()`、`_find_lab_by_article_slug()`、`GET /{slug}/lab-cta` 端点 |
| `frontend/article.html` | 新增 `<div id="lab-cta-container">` 槽位 |
| `frontend/js/article.js` | 新增 `loadLabCTA()`、`renderLabCTA()`、`_validateCtaUrl()` |
| `tests/test_article_embedded_cta.py` | 新增 — 43 tests（A-F 类） |
| `docs/labgen/ARTICLE_DETAIL_EMBEDDED_CTA_RESULT_v0.1.md` | 本文件 |
| `CHANGELOG.md` | [Unreleased] 更新 |
| `deploy/labgen/staging_ops_ticket_status.md` | G-61 条目追加 |
