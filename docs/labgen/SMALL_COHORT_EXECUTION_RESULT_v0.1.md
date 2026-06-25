# Small Cohort Execution Result v0.1

**Date**: 2026-06-25
**Operator**: Claude Code — senior dev + ops
**Cohort size**: 3（learner01 / learner02 / learner03）
**Article**: linux-files-permissions-basics
**Lab**: 6c439064-4cad-4229-addb-36927128d565（Linux Files and Permissions Basics）
**No real secrets in this document.**

---

## A. Executive Summary

**Final Decision**: `SMALL_COHORT_EXECUTION_PASSED_WITH_NOTES`

| 项目 | 结果 |
|------|------|
| Start 成功率 | 3/3 = 100% ✅ |
| Complete 成功率 | 3/3 = 100% ✅ |
| cleanup_verified=True | 3/3 = 100% ✅ |
| residual=0 | 100% ✅ |
| active sessions after run | 0 ✅ |
| tainted_vms | {} ✅ |
| error logs | 无新增异常 ✅ |
| BLOCKER | 0 ✅ |
| HIGH | 0 ✅ |
| MEDIUM（新增） | 1（MEDIUM-002，两个竞争入口）|
| feedback 收集 | 3/3 ✅ |
| 无 live LLM | ✅ |
| VMID 500-599 未触碰 | ✅ |

**WITH_NOTES 原因**：MEDIUM-002（文章页面存在两个指向不同目的地的实验入口，2/3 learner 初始被顶部导航引导至目录而非直接实验页面）。

---

## B. Session 数据

| learner | session_id | status | cleanup_verified | steps | started_at | ended_at | 时长 |
|---------|-----------|--------|-----------------|-------|-----------|---------|------|
| learner01 | 8b4465d0... | LAB_CLOSED | True | 4/4 | 16:25:34Z | 16:27:00Z | ~85s |
| learner02 | caf51367... | LAB_CLOSED | True | 4/4 | 16:50:11Z | 16:51:26Z | ~75s |
| learner03 | bc40a014... | LAB_CLOSED | True | 4/4 | 17:00:54Z | 17:04:07Z | ~193s |

---

## C. Post-run System Audit

| 检查项 | 状态 |
|--------|------|
| active sessions | ✅ 0 |
| tainted_vms | ✅ {} |
| residual K8s resources | ✅ 0 |
| health endpoint | ✅ `{"status":"healthy","proxmox":{"connected":true}}` |
| error logs (past 1h) | ✅ 无新增异常 |
| VMID 500-599 | ✅ 未触碰（Linux lab 使用本地 sandbox，不创建 VM）|
| source_article_id 未泄露 | ✅ |
| raw article text 未泄露 | ✅ |
| email / password_hash 未泄露 | ✅ |
| public upload route | ✅ 不存在 |
| live LLM 调用 | ✅ 0（fake_only 模式）|

---

## D. Article → CTA → Lab 流程验证

| learner | 入口路径 | Article CTA 验证 |
|---------|---------|-----------------|
| learner01 | 文章页面 → CTA → 登录 → Lab | ✅ 完整 CTA 流程（Q1 反馈确认）|
| learner02 | 直接登录 → App → LabGen 实验（header nav）→ Catalog → Lab | ⚠️ 绕过了文章 CTA |
| learner03 | 文章页面 → 先点顶部 header nav（目录）→ 退出 → 底部 CTA → 登录 → Lab | ✅ 最终经由底部嵌入式 CTA 进入 |

**结论**：Article → 嵌入式 CTA → Lab 链路技术上验证通过（learner01 完整路径 / learner03 底部 CTA）。Header nav "进入实验室" 作为竞争入口引发混淆（见 MEDIUM-002）。

---

## E. 10-Q 反馈汇总

| Q | learner01 | learner02 | learner03 |
|---|-----------|-----------|-----------|
| Q1 文章入口 | ✅ 顺利 | ⚠️ 未经文章 CTA | ✅ 找到（顶+底两个入口）|
| Q2 CTA 文案 | ✅ 清晰 | — | ✅ 清晰 |
| Q3 注册/登录 | ✅ 直接登录 | ✅ 直接登录 | ✅ 直接登录 |
| Q4 实验背景 | ✅ 清晰 | — | ✅ 清晰 |
| Q5 步骤 | ✅ 清晰 | — | ✅ 清晰 |
| Q6 命令可操作 | ✅ 容易复制 | ✅ 容易复制 | ✅ 容易复制 |
| Q7 Check 反馈 | ✅ 有帮助 | ✅ 有帮助 | ✅ 有帮助 |
| Q8 最困难步骤 | 无 | 无 | 无 |
| Q9 需要帮助 | 否 | 否 | 否 |
| Q10 继续意愿 | ✅ "读了能马上验证，非常新鲜" | ✅ "感兴趣内容会乐意动手" | ✅ "真实厂线案例/资深工程师方案，会订阅" |

**Q10 亮点**：
- learner01："读了网站能马上验证网站内容，非常新鲜"——验证了"读了能练"核心价值主张
- learner03："如果文章是真实厂线案例以及资深工程师的解决方案，我会订阅"——明确了内容质量方向：实战案例 > 入门教程

---

## F. Issue Triage

| 级别 | 编号 | 状态 | 描述 |
|------|------|------|------|
| BLOCKER | — | 0 | — |
| HIGH | — | 0 | — |
| MEDIUM | MEDIUM-001 | ✅ pre-cohort 已修复 | CTA redirect 缺 `?next=`（G-64 修复）|
| MEDIUM | MEDIUM-002 | 🔴 新增 | 文章页面两个竞争实验入口指向不同目的地 |
| LOW | — | 0 | — |
| NOTE | NOTE-001 | — | 3位 learner 均为技术从业者，完成时长 75–193 秒（远快于预计 20 分钟），代表技术用户基线，非普通用户基线 |
| NOTE | NOTE-002 | — | 凭证通过 operator session 直接传递，未验证"新用户自主注册 → CTA 重定向"路径（MEDIUM-001 修复的真实路径）|

### MEDIUM-002 详情

**问题**：在文章页面登录状态下，用户看到两个视觉上并列的实验入口：
1. **Header nav** "进入实验室"（右上角）→ `/labgen-catalog.html`（目录，需自行找到对应实验）
2. **嵌入式 CTA** "进入实验"（文章内容底部）→ `/labgen-lab.html?labId=6c439064...`（直接进入）

**观测**：
- learner02：点击 header nav → 进入 catalog → 自行找到实验（绕过 CTA）
- learner03：先点 header nav → catalog → 退出 → 回到文章 → 底部 CTA → 直接进入

**影响**：Article → CTA → Lab 的意图链路被 header nav 干扰，2/3 learner 初始被分流。learner02 未观测到嵌入式 CTA 的完整路径。

**根因**：Header nav 的"进入实验室"是全局导航，设计上与嵌入式 CTA 目的地不同，但视觉上优先级不低于 CTA，在文章页面形成竞争。

**Fix direction**（不在本任务执行，记录供下一任务）：
- 方案 A：文章页面隐藏或降权 header nav 中的"进入实验室"，强化嵌入式 CTA 视觉优先级
- 方案 B：在文章页面的 header nav 中将"进入实验室"换成文章对应的实验直链（`/labgen-lab.html?labId=...`），与底部 CTA 目的地一致
- 方案 B 更符合"读了能练"的意图，不需要用户在目录中再找一次

---

## G. Success Criteria 达成情况

| 标准 | 阈值 | 实际 | 达成 |
|------|------|------|------|
| 所有 learner 打开文章页面 | 100% | learner01/03 ✅；learner02 ⚠️ 未经文章进入 | 部分 |
| 所有 learner 看到 CTA | 100% | learner01/03 ✅；learner02 未见 CTA | 部分 |
| 所有 learner 能注册/登录 | 100% | 3/3 ✅ | ✅ |
| Start 成功率 | ≥ 80% | 100% | ✅ |
| Complete 成功率 | ≥ 80% | 100% | ✅ |
| cleanup_verified=True | 100% | 100% | ✅ |
| residual=0 | 100% | 100% | ✅ |
| active sessions after run = 0 | 100% | ✅ | ✅ |
| taint clean | 100% | ✅ | ✅ |
| 所有安全暴露检查 | 100% PASS | ✅ | ✅ |
| 每位 learner 有 feedback | 100% | 3/3 ✅ | ✅ |
| 无 BLOCKER / HIGH | 100% | ✅ | ✅ |

---

## H. Final Decision 理由

```
SMALL_COHORT_EXECUTION_PASSED_WITH_NOTES
```

**PASSED**：
1. 3/3 LAB_CLOSED cleanup_verified=True（100% 技术闭环）
2. 0 BLOCKER / 0 HIGH
3. active=0, tainted={}, residual=0, 错误日志干净
4. 10-Q feedback 3/3 收集，Q10 质量高，核心价值主张"读了能练"被 learner01 自发表达
5. learner03 完整验证了 Article → 嵌入式 CTA → Login → Lab → Complete 链路

**WITH_NOTES**：
1. MEDIUM-002：两个竞争入口干扰了 learner02 和 learner03（初始）的 CTA 路径
2. learner02 完全绕过文章 CTA，Article CTA 链路对其未被观测
3. 3 位 learner 均为技术从业者，完成时间极短（75–193 秒），未覆盖普通技术用户场景

---

## I. 下一步推荐

**立即行动（MEDIUM-002 修复）**：
- 调整文章页面 header nav "进入实验室"行为，使其在文章页面指向文章对应的实验直链，消除两个入口的目的地差异
- 或在文章详情页将 header nav 入口降权/隐藏，强化嵌入式 CTA 的唯一性

**修复后**：
- 可进行第二轮 Small Cohort（3–5 人，引导从文章 CTA 进入，不提前传达 App 入口）
- 或扩展到更广泛受众（10–20 人）

**内容方向**（来自 learner03 Q10）：
- 真实厂线案例 + 资深工程师解决方案 > 入门教程
- 内容质量是订阅/留存的关键驱动因素

---

## J. 保留账号状态

| 账号 | 处置 | 理由 |
|------|------|------|
| learner01 | 保留（由 owner 决定） | session 已 LAB_CLOSED，无残留 |
| learner02 | 保留（由 owner 决定） | session 已 LAB_CLOSED，无残留 |
| learner03 | 保留（由 owner 决定） | session 已 LAB_CLOSED，无残留 |

账号状态：已登录态，无 admin 权限，无 draft/internal 访问。

---

*No real secrets, no learner PII beyond username, no account passwords in this document.*
*Cohort execution complete. 2026-06-25.*
