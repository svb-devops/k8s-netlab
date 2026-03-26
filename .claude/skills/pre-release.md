---
name: pre-release
description: Pre-release quality gate for k8s-netlab. Runs automatically before any release/tag operation. Six gates must all pass — test suite, CHANGELOG updated, clean working tree, no secrets in diff, production health, smoke test.
---

# pre-release

**触发时机**：用户说"发版"、"打 tag"、"准备上线"时，在执行 `release.md` 流程**之前**自动运行。

发版质量门禁，六项全部通过才允许继续发版流程。

---

## Gate 1：测试套件

```bash
source venv/bin/activate && pytest tests/ -x -q --tb=short --cov=backend --cov-report=term-missing
```

- 256 passed，覆盖率 ≥ 75% → ✅
- 有失败或覆盖率不足 → ❌ 停止，不得发版

---

## Gate 2：CHANGELOG 已更新

检查 `CHANGELOG.md` 的 `[Unreleased]` 段是否有内容（不能是空段）：

```bash
python3 -c "
import re
content = open('CHANGELOG.md').read()
m = re.search(r'## \[Unreleased\](.*?)## \[', content, re.DOTALL)
body = m.group(1).strip() if m else ''
print('有内容' if body else '空段')
"
```

- 有内容 → ✅
- 空段 → ❌ 停止，要求先补充本次变更记录

---

## Gate 3：无未提交改动

```bash
git status --porcelain
```

- 输出为空 → ✅
- 有未提交文件 → ❌ 停止，列出文件，要求先处理

---

## Gate 4：diff 无敏感内容

```bash
git diff HEAD~1..HEAD -- . ':(exclude)*.json' | grep -E "(password|secret|token|private_key)" -i | head -10
```

- 无匹配 → ✅
- 有匹配 → ❌ 停止，列出匹配行，人工确认

---

## Gate 5：生产服务健康

```bash
curl -sf https://lab.cloudnetops.tech/api/health
```

- 返回 `{"status":"healthy"}` → ✅
- 失败 → ⚠️ 警告（不阻断，但要求用户确认是否继续）

---

## Gate 6：smoke test

```bash
bash scripts/smoke_test.sh
```

- 全部端点通过 → ✅
- 有失败 → ❌ 停止，报告具体端点

---

## 通过后

所有 gate 通过，输出：

```
✅ 发版前检查全部通过，可以执行发版流程
当前版本：<从 CHANGELOG 读取最新版本号>
建议下一版本：<patch/minor/major 建议>
```

然后按 `.claude/rules/release.md` 继续。

---

## 下一步推荐

- 全部通过 → 执行 `.claude/rules/release.md` 发版流程
- Gate 1 失败（测试不过）→ 用 `skills/investigate.md` 定位失败原因
- Gate 6 失败（smoke test）→ 用 `/project:smoke-test` 单独排查，或 `skills/debug-vm.md`（若涉及 VM）
- 发版完成后 → 运行 `/project:smoke-test` 做生产验证
