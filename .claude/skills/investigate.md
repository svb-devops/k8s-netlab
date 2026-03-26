---
name: investigate
description: Systematic bug investigation for k8s-netlab. Use when user reports errors, unexpected behavior, or "why is this broken". Four phases: collect facts, narrow scope, hypothesize root cause, implement fix. Iron law — no fix without confirmed root cause.
---

# investigate

**触发时机**：用户报告 bug、异常行为、"为什么不工作"时主动推荐。
**铁律：没有确认根因，不写一行修复代码。**

四个阶段严格顺序执行，不得跳跃。

---

## 阶段一：INVESTIGATE — 收集事实

不猜测，只收集可观测的事实：

```bash
# 1. 服务当前状态
systemctl status k8s-netlab --no-pager

# 2. 最近错误日志（不加过滤，看原始输出）
journalctl -u k8s-netlab -p err --since "30 minutes ago" --no-pager

# 3. 相关数据文件当前状态
cat data/sessions.json | python3 -m json.tool 2>/dev/null | head -50
cat data/users.json | python3 -m json.tool 2>/dev/null | head -30
```

读取报告 bug 的相关代码文件（不要只看 main.py，追到实际执行路径）。

输出：**事实清单**（只写观察到的，不写推断）

---

## 阶段二：ANALYZE — 缩小范围

对事实清单进行交叉验证，排除不相关路径：

- 错误发生在哪一层？（API 路由 / 业务逻辑 / 数据存储 / 外部依赖）
- 是否可复现？触发条件是什么？
- 最近哪次 commit 改动了这个路径？

```bash
git log --oneline -20
git log --oneline --follow -10 -- <相关文件>
```

输出：**缩小后的可疑范围**（≤3 个候选位置）

---

## 阶段三：HYPOTHESIZE — 提出根因假设

对每个候选位置，提出一个具体的根因假设：

格式：
```
假设 N：<具体的代码行为描述>
验证方法：<如何用现有数据或测试证伪/证实>
置信度：高 / 中 / 低
```

**不允许的假设**：
- "可能是环境问题"（太模糊）
- "也许是并发导致的"（没有具体机制）

选置信度最高的假设，写出验证步骤。

---

## 阶段四：IMPLEMENT — 修复并固化

根因确认后：

1. **先写回归测试**，复现 bug（测试必须先 fail）
2. **修代码**，让测试 pass
3. **跑全量测试**，确认无副作用：
   ```bash
   source venv/bin/activate && pytest tests/ -x -q --tb=short
   ```
4. 按 `.claude/rules/bug-fix.md` 完成 CHANGELOG + commit + push

---

## 输出格式

```
[调查] 事实清单：...
[分析] 可疑范围缩小到：...
[假设] 根因：... | 置信度：高
[验证] 回归测试：tests/test_xxx.py::test_yyy → 复现成功
[修复] 改动：backend/xxx.py:NN
[结果] 全量测试通过，根因已固化为回归测试
```

---

## 下一步推荐

- 修复完成后 → 运行 `/project:smoke-test` 确认生产无影响
- 若涉及 VM 基础设施问题 → 改用 `skills/debug-vm.md`
- 若经验值得留存 → 立即写入 `/root/kb/topics/mistakes/`
