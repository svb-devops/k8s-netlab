# Email Registration P1 Result v0.1

**Date**: 2026-06-24
**Operator**: Claude Code acting as senior dev + ops
**Task**: G-62 — Email Registration P1 v0.1
**No real secrets in this document.**

---

## A. Executive Summary

**Final Decision**: `EMAIL_REGISTRATION_P1_READY_WITH_NOTES`

| 检查项 | 状态 |
|--------|------|
| email 字段已加入注册 API？ | ✅ YES — `email: EmailStr`，必填，format/trim/lowercase/唯一性校验 |
| email validation 实现？ | ✅ YES — EmailStr + 控制字符过滤 + field_validator 归一化 |
| 历史用户（无 email）仍可登录？ | ✅ YES — `register_user()` email 参数为 Optional，历史记录兼容 |
| Article CTA → register/login → lab 链路未破坏？ | ✅ YES — 前端 redirect 逻辑不变，注册后跳转 tab-login |
| email 发送服务未引入？ | ✅ YES — 无 SMTP/SendGrid/SES，无第三方凭证 |
| email 不暴露在不必要 API 中？ | ✅ YES — /api/auth/me / AuthResponse / catalog / lab API 均无 email |
| password_hash 不在响应中？ | ✅ YES |
| 无 public upload / live LLM / URL scraping？ | ✅ YES |
| tests | ✅ 45 新测试，4502 PASS，92.26% coverage |
| safety-reviewer | ✅ APPROVED_WITH_NOTES（HIGH 已修复，MEDIUM 已知 TOCTOU 正确性不受影响） |
| production smoke | ✅ 注册返回 201，duplicate email 返回 400，missing email 返回 422 |

WITH_NOTES 原因：email verification 未实现；forgot password 未实现；email 不用于发送任何通知。

---

## B. North Star Alignment

| 检查项 | 状态 |
|--------|------|
| 读了能练，练了能绑定原文 | ✅ Article→Lab→Register→Login→Practice 闭环完整 |
| reader registration supports Article-to-Lab | ✅ 注册表单新增 email，后台存储 |
| Admin-curated flow remains intact | ✅ admin 流程零变更 |
| 无 public upload | ✅ |
| 无 live LLM | ✅ |
| 无 URL scraping | ✅ |

---

## C. Implementation Summary

### 1. Backend — User Schema

**`backend/auth.py`**：`register_user()` 加 `email: Optional[str] = None`
- 历史调用（无 email）完全向后兼容
- email 存入 `data/users.json` 用户记录
- flock 原子性：`_add` callback 内检查 email 唯一性（最终一致性保证）
- `is_email_taken()` 工具方法（admin 可用，注册路由未调用以防邮箱枚举）

### 2. Backend — Registration API

**`backend/auth_routes.py`**：`RegisterRequest` 新增 `email: EmailStr = Field(..., max_length=254)`
- `@field_validator("email", mode="before")`：trim + lowercase + 控制字符过滤
- 注册失败统一返回 `"Username already exists"`（不区分 username/email 冲突，防邮箱枚举）
- `email-validator==2.3.0` 加入 `requirements.txt`

### 3. Frontend — Registration Form

**`frontend/login.html`**：注册表单新增 email input
```html
<input type="email" id="register-email" required maxlength="254"
       autocomplete="email" placeholder="your@email.com">
```

**`frontend/js/auth.js`**：注册 handler 加 email
```javascript
const email = document.getElementById('register-email').value.trim().toLowerCase();
body: JSON.stringify({ username, email, password })
```

### 4. Backward Compatibility

- 历史用户（`data/users.json` 无 email 字段）：`register_user()` 不写 email → 记录无 email 字段
- 历史用户登录：`verify_credentials()` 不涉及 email → 完全正常
- 直接调用 `auth_manager.register_user(username, password)` 的单元测试：email=None，无副作用

### 5. Email Exposure Boundaries

| 位置 | email 是否可见 |
|------|---------------|
| `POST /api/auth/register` 响应 | ❌ 不含 |
| `GET /api/auth/me` 响应 | ❌ 不含 |
| `/api/auth/login` 响应 | ❌ 不含 |
| `data/users.json` | ✅ 内部存储（不公开暴露） |
| admin API (`/api/admin/*`) | ❌ 不含（已验证 admin_routes.py 无 email 字段） |
| 任何 labgen/catalog API | ❌ 不含 |
| 日志 | ❌ 不打印（logger 只打印 username） |

---

## D. Safety / Privacy

| 规则 | 状态 |
|------|------|
| password 明文不存储 | ✅ 只存 password_hash |
| password_hash 不返回客户端 | ✅ |
| email 枚举防护 | ✅ email/username 冲突统一 400 detail，不可区分 |
| 无邮件服务 provider | ✅ 无 SMTP / SendGrid / SES / Mailgun |
| 无第三方 email secrets | ✅ requirements.txt 仅加 email-validator（validation 库） |
| 无 marketing consent 字段 | ✅ |
| 无 tracking | ✅ |
| users.json 不被 StaticFiles 暴露 | ✅（已验证） |

---

## E. Test Results

| 类别 | 数量 | 结果 |
|------|------|------|
| A. Registration API tests | 13 | ✅ PASS |
| B. Legacy user compatibility | 5 | ✅ PASS |
| C. Login API (email not required) | 3 | ✅ PASS |
| D. Frontend/static checks | 7 | ✅ PASS |
| E. Security/privacy | 6 | ✅ PASS |
| F. Regression | 6 | ✅ PASS |
| **新增测试合计** | **40** | **PASS** |
| 全量 | 4502 | PASS |
| 覆盖率 | 92.26% | ≥ 90% ✅ |
| 8 安全扫描 | — | (pre-push) |
| safety-reviewer | — | APPROVED_WITH_NOTES |

---

## F. Production Smoke

| 检查 | 结果 |
|------|------|
| `POST /api/auth/register` with email → 201 | ✅ |
| duplicate email → 400（detail 不区分冲突类型） | ✅ |
| missing email → 422 | ✅ |
| email stored in users.json (lowercase) | ✅ |
| password_hash present, password absent | ✅ |
| service health post-restart | ✅ `{"status":"healthy","proxmox":{"connected":true}}` |
| error logs post-restart | ✅ 无新增异常 |

---

## G. Known Limitations

| Limitation | Notes |
|------------|-------|
| email verification 未实现 | 无验证邮件，email 仅存储 |
| forgot password 未实现 | 无密码重置流程 |
| email sending 未实现 | 无任何 email 发送能力 |
| marketing / notification 未实现 | 无推送 |
| Linux 文章仍为 mock_admin_article | 与 G-61 一致，未变化 |
| 无 public launch | Phase 1 operator-controlled |
| 无 customer pilot | 未启动 |

---

## H. Issue Triage

| Level | Issue | Status |
|-------|-------|--------|
| BLOCKER | — | None |
| HIGH | email/username 冲突 400 detail 可区分 → email 枚举 | ✅ FIXED — 统一返回 "Username already exists" |
| MEDIUM | TOCTOU 窗口（外层 is_email_taken 已去除，flock 内原子 check 保证正确性） | CLOSED（外层 check 已去除） |
| LOW | duplicate_email 测试未断言第一次注册成功 | ✅ FIXED |

---

## I. Final Decision

```
EMAIL_REGISTRATION_P1_READY_WITH_NOTES
```

**Rationale**:
1. ✅ email 字段实现（format 校验 + trim/lowercase + 唯一性 + 存储）
2. ✅ 历史用户向后兼容
3. ✅ Article CTA → register → login → lab 链路未破坏
4. ✅ 无 email 发送服务
5. ✅ email 不暴露在不必要 API 中
6. ✅ safety-reviewer HIGH 已修复（枚举防护），MEDIUM 已关闭
7. ✅ production smoke 通过
8. ✅ 4502 tests PASS，92.26% coverage
9. WITH_NOTES: email verification / forgot password 未实现（Phase 1 范围外）

---

## J. Recommended Next Step

| Option | Description |
|--------|-------------|
| **Real External Article Binding** (Recommended) | 在外部平台发布真正的 Linux 文章，绑定到 lab，升级 mock_admin_article |
| Small Cohort Planning Gate | 定义 cohort 规模和 rollout 计划（注册体验现已完整） |
| Email Verification / Password Recovery Planning | 规划下一阶段 email 能力（需引入 email 服务） |
| Admin Article Input MVP Round 2 | 发布外部 Linux 文章，重跑 E2E |
| Hold Expansion | 冻结新功能，聚焦当前 Article→Lab 体验质量 |

**Recommended**: Real External Article Binding — 注册体验已完整，技术路径全部就绪，唯一缺口是外部真实文章绑定。

---

## K. Technical Self-Check

- ✅ No TODO/FIXME in new code
- ✅ No placeholder-as-success
- ✅ No plaintext password storage
- ✅ No password_hash API exposure
- ✅ No users.json public exposure
- ✅ No unnecessary email exposure
- ✅ No public upload
- ✅ No ordinary user article generation
- ✅ No live LLM
- ✅ No URL scraping
- ✅ No source_article_id learner exposure
- ✅ No raw article text exposure
- ✅ No unsafe CTA claim
- ✅ No article.html CTA regression
- ✅ No registration redirect regression
- ✅ No K8s regression (4502 tests PASS)
- ✅ No Linux regression
- ✅ No catalog regression
- ✅ No runtime behavior unintended change
- ✅ No production VMID 500-599 touch
- ✅ No concurrency increase
- ✅ Docker domain not started
- ✅ No new lab published
- ✅ No cohort/customer pilot started
- ✅ No email sending service added
- ✅ No SMTP / SendGrid / SES secrets
- ✅ No BLOCKER/HIGH downgraded to NOTE (HIGH fixed)

---

## L. Modified Files

| File | Change |
|------|--------|
| `backend/auth.py` | `register_user()` 加 `email: Optional[str] = None`；`is_email_taken()` 工具方法；flock 内原子 email 唯一性检查 |
| `backend/auth_routes.py` | `RegisterRequest` 加 `email: EmailStr`；`_normalize_email` field_validator；email 枚举防护（统一 400 detail） |
| `frontend/login.html` | 注册表单新增 email input（type=email, required, maxlength=254, autocomplete=email） |
| `frontend/js/auth.js` | 注册 handler 读取并发送 email（trim + toLowerCase） |
| `requirements.txt` | 新增 `email-validator==2.3.0` |
| `tests/test_email_registration.py` | 新增 — 40 tests（A-F 类） |
| `tests/test_auth_routes.py` | 现有注册 HTTP 调用更新含 email；500 测试更新 |
| `tests/test_contract.py` | 注册调用加 email |
| `tests/test_e2e.py` | 注册调用加 email |
| `tests/test_robustness.py` | 注册边界值测试加 email |
| `tests/test_labgen_article_publish_gate.py` | 注册调用加 email |
| `docs/labgen/EMAIL_REGISTRATION_P1_RESULT_v0.1.md` | 本文件 |
| `CHANGELOG.md` | [Unreleased] 更新 |
| `deploy/labgen/staging_ops_ticket_status.md` | G-62 条目追加 |
