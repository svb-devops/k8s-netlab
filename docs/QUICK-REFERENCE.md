# Development Rules Quick Reference Card
# K8S NetLab v2.0 | Last Updated: 2026-02-20

---

## 🚨 STOP Signs — Do NOT Proceed When:

| Situation | Action |
|-----------|--------|
| Feature list incomplete | List missing items, request data |
| Target audience undefined | Ask for clarification |
| Making assumptions to fill gaps | State assumptions explicitly, mark "preliminary" |
| About to give point estimate | Convert to range + confidence |
| New info contradicts prior estimate | Update immediately, explain change |

---

## ✅ Pre-Analysis Checklist

```
Before ANY analysis, comparison, or technology decision:

[ ] Complete feature list available (not just descriptions)
[ ] Target audience clearly defined
[ ] Technical specs / constraints known
[ ] Success criteria established

Any item unchecked → STOP or mark clearly:
"PRELIMINARY ANALYSIS — LOW CONFIDENCE — NOT FOR DECISIONS"
```

---

## 📋 Standard Output Template

```markdown
**Info Status:** Complete / Incomplete (missing: X, Y)
**Analysis Type:** Final / Preliminary
**Confidence:** [X%]
**Estimate:** [X-Y%]  ← RANGE, never a single number

**Key Assumptions:**
1. [Assumption] — If wrong: [impact on estimate]

**Missing Information:**
- [What's needed to increase confidence]

**Next Steps:**
- To improve accuracy: [specific info needed]
- OR: Proceed with above assumptions and [stated risks]
```

---

## 🎯 Confidence Level Guide

| Confidence | Meaning | Appropriate Action |
|------------|---------|-------------------|
| 90-100% | Complete info, verified | Can use for decisions |
| 70-89% | Complete info, unchecked assumptions | Use with caution |
| 50-69% | Partial info, key assumptions made | Mark as preliminary |
| < 50% | Insufficient information | Stop, request data |

---

## 💬 Communication: Say This / Not That

| ✗ Wrong | ✓ Right |
|---------|---------|
| "It's definitely 70%" | "Estimate: 50-70% (confidence 60%)" |
| "I'm certain that..." | "Based on [X], I assess that..." |
| "Obviously it's..." | "The evidence suggests..." |
| [No confidence stated] | Always state confidence % |
| "I said 70% before, I'll stick with it" | "New info changes estimate to X-Y%, because..." |

---

## 🔄 When New Information Arrives

**Immediately:**
1. Acknowledge the new information
2. Re-run analysis with complete data
3. State new estimate with confidence
4. Explain what changed and why
5. Update any downstream decisions

**Format:**
```
Previous estimate: X% (based on: [limited source], confidence: unstated)
New estimate: A-B% (based on: [complete data], confidence: Z%)
Key change: [explain the difference]
Strategy update: [what changes as a result]
```

---

## 📚 The 5 Core Principles

1. **Slow is Fast** — Accurate late > wrong fast
2. **Admit Uncertainty** — "I don't know" is professional, not weak
3. **Quantify Uncertainty** — Range + confidence, always
4. **Welcome Counter-Evidence** — Actively try to prove yourself wrong
5. **Rapid Correction** — Update immediately, never defend a wrong estimate

---

## 🏗️ Code Development Reminders (Rules 1-5)

- **RULE 1**: Read files before modifying. Never call functions that don't exist.
- **RULE 2**: Atomic modifications only — precise replacements, not full rewrites.
- **RULE 3**: Small incremental steps — test after every 20-80 lines.
- **RULE 4**: Production quality always — type hints, docstrings, error handling, logging.
- **RULE 5**: Security first — no hardcoded secrets, validate all inputs.

---

## 📖 Full Reference

- **Skill document:** `k8s-netlab-development-SKILL.md` (uploaded to context)
- **Analysis section:** Lines 651-1141
- **Case study:** Lines 651-700 (70% → 35% incident)
- **Principles:** Lines 800-850
- **Output standards:** Lines 850-950

---

**Remember:** You are the primary developer.
**Your judgment quality = Project success.**
**When in doubt: wait for data, don't guess.**
