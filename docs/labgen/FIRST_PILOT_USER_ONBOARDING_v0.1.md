# First Pilot User Onboarding v0.1

**Pilot nature**: Early MVP pilot — NOT production, NOT SLA-backed, NOT for general use.

---

## Target Audience

- **Users**: 1 trusted user (maximum 1-2 whitelisted users during this pilot window)
- **Nature**: Early MVP pilot — internal trusted testers only
- **SLA**: None. The environment may be interrupted without notice.
- **Data**: No personal data should be entered. Experiments may be reset.
- **Purpose**: Feedback on whether the lab can be entered, steps are clear, verifier feedback is useful, and the completion flow is smooth.

---

## Pilot Lab

| Field | Value |
|-------|-------|
| Lab ID | `67fca5e4-2e8a-4c51-b62e-f3b8f6bd1fd6` |
| Title | Kubernetes Basics: Your Isolated Lab Environment |
| Duration | ~10 minutes |
| Step count | 1 |
| Action required | None (observation step) |

The pilot user will:
1. Start the lab
2. Read the namespace isolation explanation
3. Click "Check Step"
4. Receive verification confirmation
5. Complete the lab

---

## Resource Limits (Current)

| Limit | Value |
|-------|-------|
| Max concurrent sessions | 1 |
| Max staging VMs | 3 (VMID 400-499 only) |
| LLM | Disabled |
| Production VMID 500-599 | Not used in this pilot |
| HA | No (VM 401 single node) |

---

## Feedback Focus

Please capture feedback on:

- [ ] Can the user enter the lab without errors?
- [ ] Are the step instructions clear?
- [ ] Is the verifier feedback useful? (pass/fail message)
- [ ] Does the completion flow feel smooth?
- [ ] Which step caused the most confusion?

---

## Pilot Window

Pilot window is time-boxed and small-scale. Operator (Claude Code) retains emergency stop capability at all times.

---

## Emergency Stop Contact / Procedure

If anything fails during the pilot:

1. Operator stops session manually (see rollback plan in FIRST_PILOT_LAB_RELEASE_RESULT_v0.1.md)
2. Pilot window ends immediately
3. No customer support SLA exists — operator handles all issues directly

To stop the pilot immediately:
```bash
# Set LABGEN_RUNTIME_MODE=dev in .env and restart
systemctl restart k8s-netlab.service
```

---

## Current Resource Limits (Reconfirmed)

- max concurrent sessions = 1
- max staging VMs = 3
- LLM disabled
- No production VMID 500-599 usage
- No HA production environment

---

## What Is NOT Exposed to the Pilot User

- Admin/dev/debug pages
- Internal session IDs beyond what's needed for UX
- Kubernetes kubeconfig or service account tokens
- Verifier credentials
- Proxmox infrastructure details
- Raw Kubernetes exception bodies

---

## Acceptance Criteria to Move to Next Phase

Before expanding beyond 1-2 pilot users:

1. At least 1 user completes the full lab flow (create → check step → complete) without errors
2. No cleanup failures, no tainted VMs
3. Operator confirms no security incidents or unexpected data leaks
4. Feedback captured and reviewed

---

## Related Docs

- Release gate: `docs/labgen/FIRST_PILOT_LAB_RELEASE_RESULT_v0.1.md`
- MVP contract: `docs/labgen/MVP_ENGINEERING_CONTRACT_v0.1.md`
- Staging profile: `docs/labgen/HOME_LAB_MVP_STAGING_PROFILE_v0.1.md`
- Pilot gate: `docs/labgen/HOME_LAB_MVP_PILOT_GATE_RESULT_v0.1.md`
