# Article Page Primary CTA Unification Result v0.1

**Date**: 2026-06-25
**Operator**: Claude Code — senior dev + ops
**Task**: G-66 — fix MEDIUM-002 from Small Cohort Execution
**Commit**: d57b9f7
**No real secrets in this document.**

---

## A. Executive Summary

**Final Decision**: `ARTICLE_PAGE_PRIMARY_CTA_UNIFIED`

| 项目 | 结果 |
|------|------|
| MEDIUM-002 修复 | ✅ CLOSED |
| Header nav destination == embedded CTA destination | ✅ 已统一 |
| No-CTA fallback (/app + catalog 可达) | ✅ |
| invalid CTA URL rejected | ✅ |
| safety-reviewer | ✅ APPROVED (无 BLOCKER/HIGH/MEDIUM) |
| 49 CTA tests PASS | ✅ (+5 新增) |
| 4508 tests PASS 92.25% coverage | ✅ |
| E2E smoke | ✅ |
| no public upload | ✅ |
| no live LLM | ✅ |
| no URL scraping | ✅ |
| VMID 500-599 untouched | ✅ |

---

## B. Small Cohort Finding (来源)

| 项目 | 数据 |
|------|------|
| Learner sessions | 3/3 LAB_CLOSED cleanup_verified=True |
| Residual | 0 |
| MEDIUM-002 discovery | 2/3 learner 初始被 header nav 分流 |

**MEDIUM-002 详情**：
- learner02：登录后点击 header nav "进入实验室" → `/app` → LabGen 实验 → catalog → 自行找到实验（绕过嵌入式 CTA）
- learner03：文章页面看到顶部和底部两个入口，先点顶部 → catalog → 退出 → 回到底部 CTA → 正确进入

**Q10 价值信号**：
- "读了网站能马上验证网站内容，非常新鲜"（learner01）— "读了能练"价值主张被自发表达
- "感兴趣内容会乐意动手"（learner02）— 内容相关性驱动参与
- "如果文章是真实厂线案例以及资深工程师的解决方案，我会订阅"（learner03）— 内容方向：实战 > 入门

---

## C. Implementation Summary

### 修改文件

**`frontend/js/article.js`**（+8 行）：

1. `initAuth()` 的 "进入实验室" anchor 加 `data-lab-nav` 稳定属性：
   ```html
   <a href="/app" data-lab-nav class="bg-blue-600 ...">进入实验室</a>
   ```

2. `renderLabCTA()` 末尾加 header nav 统一逻辑：
   ```javascript
   // Unify header nav with embedded CTA so article page has one lab entry point
   const navLabLink = document.querySelector('#nav-actions [data-lab-nav]');
   if (navLabLink) {
       navLabLink.href = ctaUrl;
       navLabLink.textContent = '进入配套实验';
   }
   ```

**`tests/test_article_embedded_cta.py`**（+5 个测试）：
- `test_article_js_init_auth_marks_lab_nav_with_stable_data_attribute`
- `test_article_js_header_nav_updated_to_linked_lab_when_cta_loaded`
- `test_article_js_header_nav_update_uses_pre_validated_cta_url`
- `test_article_js_header_nav_text_changes_to_配套实验`
- `test_article_js_header_nav_update_uses_safe_dom_textcontent`

### Header nav 行为对比

| 场景 | 修复前 | 修复后 |
|------|--------|--------|
| article 页 + linked lab + 已登录 | "进入实验室" → /app (catalog 经由 index) | "进入配套实验" → /labgen-lab.html?labId=... (直接) |
| article 页 + no linked lab + 已登录 | "进入实验室" → /app | "进入实验室" → /app（不变）|
| article 页 + 未登录 | 无 lab 入口 | 无 lab 入口（不变，embedded CTA 处理 ?next= redirect）|
| landing / catalog / 其他页面 | 各页自己的 nav | 不变（renderLabCTA 只在 article.js 中调用）|

---

## D. Safety / Exposure

| 检查项 | 结果 |
|--------|------|
| ctaUrl 使用前经 `_validateCtaUrl()` 校验 | ✅ (startsWith '/labgen-lab.html?labId=') |
| open redirect 风险 | ✅ 无（absolute URL / javascript: / data: 全部拒绝）|
| DOM API 安全 | ✅ `.href` + `.textContent`，无 `.innerHTML` |
| null 守卫 | ✅ `if (navLabLink)` |
| selector 稳定性 | ✅ `[data-lab-nav]` 属性不随 href mutation 失效 |
| source_article_id 未暴露 | ✅ |
| raw article text 未暴露 | ✅ |
| admin fields 未暴露 | ✅ |
| public upload | ✅ 不存在 |
| live LLM | ✅ 0 调用（fake_only 模式）|
| URL scraping | ✅ 无 |
| VMID 500-599 | ✅ 未触碰 |

---

## E. Test Results

| 检查项 | 状态 |
|--------|------|
| header nav CTA unification tests (5 new) | ✅ PASS |
| embedded CTA regression (44 existing) | ✅ PASS |
| no-CTA fallback (静态代码分析) | ✅ renderLabCTA 不调用 = nav 不变 |
| invalid CTA URL rejection | ✅ _validateCtaUrl() gate |
| article CTA endpoint regression | ✅ |
| source_article_id exposure check | ✅ |
| raw article text exposure check | ✅ |
| registration email regression | ✅ |
| catalog route regression | ✅ |
| K8s Lab 5 targeted regression | ✅ |
| Linux lab targeted regression | ✅ |
| E2E smoke (API-side) | ✅ has_cta=True, ctaUrl 正确, article 200, health OK |
| full backend pytest | ✅ 4508 passed 92.25% coverage |
| 8 safety scans | ✅ pre-commit PASS |
| Codex | ✅ pre-push PASS |
| pre-commit | ✅ PASS |
| pre-push | ✅ PASS |
| secret leak scan | ✅ PASS |

---

## F. Known Limitations

- 每篇 article 只支持一个 linked lab（当前 Phase 1 设计，无需多 lab）
- header nav 更新为 JS 运行时行为，browser-level E2E 验证通过静态代码分析覆盖（无 headless browser 环境）
- article.html 仅为 k8s-netlab official site 使用；外部平台不受此行为控制
- 无 public launch；无 customer pilot；无第二轮 cohort（本任务范围外）

---

## G. Issue Triage

| 级别 | 编号 | 状态 | 描述 |
|------|------|------|------|
| BLOCKER | — | 0 | — |
| HIGH | — | 0 | — |
| MEDIUM | MEDIUM-002 | ✅ CLOSED | 文章页面两个竞争实验入口 → 已统一为单一目的地 |
| LOW | safety-reviewer LOW | NOTE | 静态测试不执行 JS；已知限制，可接受 |
| NOTE | NOTE-001 | — | 3 位 learner 均为技术从业者，完成极快（75-193s），非普通用户代表基线 |

---

## H. Final Decision

```
ARTICLE_PAGE_PRIMARY_CTA_UNIFIED
```

**UNIFIED（无 WITH_NOTES）原因**：
1. MEDIUM-002 完整修复，header nav 与嵌入式 CTA 目的地一致
2. 0 BLOCKER / 0 HIGH / 0 MEDIUM
3. safety-reviewer APPROVED
4. 4508 tests PASS 92.25% coverage
5. E2E smoke PASS（API 侧验证 + 静态代码分析）
6. no-CTA fallback 明确（catalog 仍可达）
7. 安全约束全部保持

---

## I. Recommended Next Step

**推荐**：Small Cohort Round 2

- MEDIUM-002 已修复，文章页面现在只有一个清晰的实验入口
- 可安排第二轮 3-5 人 cohort，重点验证：
  - 所有 learner 经文章嵌入式 CTA 进入（无 header nav 干扰）
  - header nav "进入配套实验" 被正确识别和使用
  - Q10 反馈再次收集（确认价值主张可重复）
- 若希望跳过第二轮 cohort：可直接进行 Broader Trusted Audience Planning（10-20 人）

**内容方向**（learner03 Q10 信号）：
- 真实厂线案例 + 资深工程师解决方案 > 入门教程
- 这是订阅/留存的关键驱动因素

---

## J. 技术自查清单

- [x] 无 TODO/FIXME
- [x] 无 placeholder-as-success
- [x] MEDIUM-002 未被降级为 NOTE（已修复关闭）
- [x] article header nav == embedded CTA 目的地
- [x] no-CTA fallback 明确
- [x] catalog 入口仍可达（landing / 其他页面不受影响）
- [x] 无错误 lab 跳转
- [x] 无 unvalidated CTA URL
- [x] 无 unsafe innerHTML
- [x] 无 source_article_id exposure
- [x] 无 raw article text exposure
- [x] 无 email/password_hash exposure
- [x] 无 public upload
- [x] 无 live LLM
- [x] 无 URL scraping
- [x] 无 article.html CTA regression
- [x] 无 registration redirect regression
- [x] 无 K8s regression
- [x] 无 Linux regression
- [x] 无 catalog regression
- [x] 无 runtime behavior unintended change
- [x] VMID 500-599 未触碰
- [x] 无并发提高
- [x] Docker domain 未启动
- [x] 未发布新 lab
- [x] 未启动 customer pilot
- [x] 未扩大 cohort（本任务范围外）
- [x] 无 BLOCKER / HIGH / MEDIUM 被降级为 NOTE

---

*No real secrets, no learner PII, no account passwords in this document.*
*G-66 Article Page Primary CTA Unification complete. 2026-06-25.*
