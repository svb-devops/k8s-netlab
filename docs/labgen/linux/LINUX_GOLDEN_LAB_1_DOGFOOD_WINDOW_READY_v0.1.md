# Linux Golden Lab #1 — Owner Dogfood Window Ready v0.1

**Gate**: "Linux Golden Lab #1 — Owner Dogfood Window" CEO/CTO brief
**Status**: `LINUX_GOLDEN_LAB_1_DOGFOOD_WINDOW_READY`
**Date**: 2026-07-21
**Prepared by**: Claude Code

---

## A. Dogfood Baseline (recorded before any change, §一)

| Item | Baseline value |
|---|---|
| `lab_id` | `a1c3f7e2-9b6d-4e12-8f4a-6d2c5e0b7a91` |
| `publish_status` | `draft` |
| `cta_enabled` / `article_url` | `False` / `None` — no CTA |
| `LABGEN_ENABLED_LAB_IDS` | 6 K8s labs only — this lab_id absent |
| `LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS` | `6c439064-...` (existing Linux basics lab) only — this lab_id absent |
| `data/labgen_invites.json` | did not exist (no lab invite-gated) |
| Active sessions for this lab | 0 |
| Residual workspace for this lab's sessions | 0 |
| `runner_ready` | `true` |
| Existing Linux lab / K8s series | unaffected, unchanged |

---

## B. Temporary Authorized Opening (§二)

Scoped to the Owner's real, pre-existing non-admin test account: **`owner-test-01`**
(same account used for the prior Pod Pending dogfood window — reused, not newly
created).

| Change | Detail | Reversible record |
|---|---|---|
| `publish_status` | Flipped `draft → published` via the **real production publish flow** (`StaticValidator.validate()` + `PublishDecisionService.evaluate()` → `ALLOWED` + `PublishService.publish()`) — not a raw JSON edit. `rehearsal_completed=True` already set from the prior internal rehearsal. | Baseline: `draft` |
| `LABGEN_ENABLED_LAB_IDS` (`.env`) | This lab_id appended, with an inline comment marking it temporary/dogfood-only and pointing back to this document | Baseline: 6 K8s lab ids (unchanged, listed above) |
| `LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS` (`.env`) | This lab_id appended | Baseline: `6c439064-...` only |
| `data/labgen_invites.json` | Created: `{"a1c3f7e2-...": ["owner-test-01"]}` | Baseline: file did not exist |
| Service restart | `systemctl restart k8s-netlab` (required for the `.env` changes to take effect) | health healthy after restart, no new error logs |

**Not done** (per explicit prohibition): no public catalog/CTA addition beyond the
allowlist entries above, no Directus article, no new commands, no runner/path
security relaxation, no analytics instrumentation added, no other Linux topic
started, no K8s change.

**Known accepted exposure** (documented, not silently glossed over): `publish_status
=published` makes this lab appear in `list_published_labs()` for *any* authenticated
user (title + summary visible), because the current catalog implementation does not
hide invite-gated-but-not-invited entries from the list — it only marks them
`is_startable=false` / `NOT_INVITED`. This is the same accepted tradeoff used for the
prior Pod Pending dogfood window (same `owner-test-01` + invite-registry mechanism).
No lab content, commands, or verifiers are exposed by this — only the title/summary
a learner catalog always shows for published labs.

---

## C. Readiness Check (§三 — read-only, no session created)

Verified via `LearnerCatalogService.evaluate_start_eligibility()` (read-only, does not
create sessions/workspaces/audit events per its own contract):

| Account | `is_startable` | Issue |
|---|---|---|
| `owner-test-01` | **`true`** | — |
| `k8s_test01` (random other non-admin) | `false` | `NOT_INVITED` |
| `lab_test` (random other non-admin) | `false` | `NOT_INVITED` |

| Check | Result |
|---|---|
| `runner_uid` / `runner_gid` | 997 / 997, not root |
| Workspace pre-created | No — 0 sessions of any status exist for `owner-test-01` on this lab |
| Prior sessions for this lab (rehearsal + smoke test artifacts) | All terminal (`LAB_CLOSED` ×2, `LAB_FORCE_CLOSED` ×1) — none active |
| `health` | `healthy`, no new error log entries since restart |
| Existing Linux lab / K8s series | Unaffected |

---

## D. Status

```
LINUX_GOLDEN_LAB_1_DOGFOOD_WINDOW_READY
```

**All operations now pause.** No further action will be taken — no simulated
walkthrough, no automated step-through, no rollback — until the Owner has personally
logged in as `owner-test-01` in a real browser session, run through Golden Lab #1
end-to-end, and explicitly reports the test as complete (per §四/§七 of the brief: the
Owner's own judgment on Step 2's wording, the article review, and the real
growth-event audit are all things only the Owner's actual session can produce —
they are not simulated here).

When the Owner reports "测试完成" (test complete), the next actions will be: read the
real session/audit records for §六's event-truth check, then execute §七's rollback
(remove the temporary invite, remove the temporary allowlist entries, revert
`publish_status` to `draft`, confirm other accounts still blocked, confirm
`active_sessions=0`/`residual_workspaces=0`/`health healthy`) — never before that
confirmation.
