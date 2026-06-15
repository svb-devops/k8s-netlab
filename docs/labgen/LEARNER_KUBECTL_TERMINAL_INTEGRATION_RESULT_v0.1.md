# Learner kubectl Web Terminal Integration Gate v0.1
**Result: LEARNER_KUBECTL_TERMINAL_READY**
Date: 2026-06-15

## A. Gate Objective

Resolve UX-H1 HIGH blocker from Real Human Learner Validation v0.1:
learners have no kubectl terminal environment → Labs 2–4 are blocked.

## B. What Was Built

### Backend

| File | Purpose |
|------|---------|
| `backend/labgen/learner_credentials.py` | Per-session SA/Role/RoleBinding + token + kubeconfig (server-side only) |
| `backend/labgen/kubectl_executor.py` | Command validation + sandboxed subprocess execution |
| `backend/labgen/lab_kubectl_ws.py` | WebSocket handler (/ws/lab-kubectl/{session_id}) |
| `backend/labgen/learner_session_snapshot.py` | Added `namespace`, `step_do`, `step_commands` to snapshot |
| `backend/main.py` | Registered WebSocket route |

### Frontend

| File | Purpose |
|------|---------|
| `frontend/labgen-session.html` | Added `#kubectl-terminal-panel` (hidden by default) |
| `frontend/js/labgen-kubectl-terminal.js` | LabKubectlTerminal class (xterm.js v5.3.0) |
| `frontend/js/labgen-session-init.js` | Terminal lifecycle via `syncTerminal(snapshot)` |
| `frontend/js/labgenViews.js` | Renders `step_do` and `step_commands` for current step |

### Tests

| File | Coverage |
|------|---------|
| `tests/test_labgen_kubectl_executor.py` | 75 tests: allowed commands, blocked subcommands, all output format bypass variants |
| `tests/test_labgen_learner_credentials.py` | UUID validation, path traversal rejection, reclaim idempotency |
| `tests/test_labgen_lab_kubectl_ws.py` | Auth rejection, snapshot content, namespace substitution |

**Final: 3328 tests PASS, 90.26% coverage**

## C. Security Architecture

### Credential isolation
- Platform kubeconfig: `/etc/labgen/home_lab_mvp.kubeconfig` (never sent to client, never logged)
- Learner kubeconfig: `/var/lib/labgen-staging/learner-kubeconfigs/{session_id}/config` (chmod 600)
- Token expiry: 3600s (short-lived SA token via TokenRequest API)
- UUID validation on session_id prevents path traversal

### RBAC (namespace-scoped only)
```
configmaps:   create/get/list/watch/delete/update/patch
secrets:      create/get/list/watch/delete  (NO raw output allowed)
pods/events:  get/list/watch (read-only)
deployments:  create/get/list/watch/delete/update/patch
replicasets:  get/list/watch
```
No ClusterRole, no pods/create, no cluster-scoped resources.

### Command validation (kubectl_executor.py)
- Only `kubectl` prefix allowed
- Blocked subcommands: exec, port-forward, proxy, attach, cp, debug, run, plugin
- Blocked patterns: config/auth/create token/cluster-scoped resources/all-namespaces/-A
- Output format: token-based check — ONLY `wide` and `name` allowed; all others blocked
  (catches -o=yaml, -ojson, -o jsonpath, -o go-template, --output yaml, etc.)
- Override prevention: --kubeconfig, -n <ns>, --namespace all blocked
- Execution: shlex.split + asyncio.create_subprocess_exec (no shell=True)
- Limits: 64KB output, 30s timeout, 2048 byte max command

### WebSocket auth (5 layers)
1. session_token cookie required
2. Token verified via auth_manager
3. Session must exist
4. Session owner must match authenticated user
5. Session must be LAB_ACTIVE

### Session lifecycle binding
- Terminal disconnects when session leaves LAB_ACTIVE (polled every 10s)
- Idle timeout: 600s
- Credentials reclaimed in finally block via get_running_loop()

## D. Safety Reviewer Findings & Resolution

**BLOCKER 1** — Output format bypass: `-o=yaml`, `-o jsonpath`, `--output yaml` not caught by regex
→ FIXED: Replaced regex with token-based `_check_output_format()` using allowlist {wide, name}

**BLOCKER 2** — `asyncio.get_event_loop()` in finally block (wrong loop risk)
→ FIXED: Changed to `asyncio.get_running_loop()`

**HIGH** — Missing tests for output format bypass variants
→ FIXED: Added parametrised tests for all bypass forms

**LOW** — Stale docstring claiming namespace not exposed
→ FIXED: Updated docstring to clarify namespace is intentionally exposed for terminal badge

**MEDIUM** — reclaim_learner_credentials swallows errors silently
→ ACCEPTED (namespace deletion by LabSessionService provides defence-in-depth; reclaim errors are logged)

## E. Constraints Compliance

| Constraint | Status |
|-----------|--------|
| 不可用 LLM | ✅ 0 LLM calls |
| 不触碰 production VMID 500-599 | ✅ |
| 不暴露 platform kubeconfig | ✅ kubeconfig never sent/logged |
| 不暴露 verifier credential | ✅ |
| 不给 learner cluster-admin | ✅ namespace-scoped SA only |
| 不允许跨 namespace 访问 | ✅ -n/-A blocked + RBAC enforced |
| WebSocket 必须鉴权 | ✅ 5-layer auth |
| session closed 后 terminal 立即不可用 | ✅ 10s poll + LAB_ACTIVE check |
| 有 command audit logging | ✅ session_id/user/namespace/cmd/exit_code/elapsed |
| 不在日志记录 token/kubeconfig | ✅ confirmed |
| 有 idle timeout | ✅ 600s |
| 必须有真实可执行 kubectl | ✅ /usr/local/bin/kubectl v1.33.0 |

## F. Next Steps

1. **Internal rehearsal**: Start ConfigMap lab as k8s_test, use terminal to create configmap, Check Step → PASS, Complete → LAB_CLOSED
2. **Security negative test**: Try `kubectl get namespaces`, `-o yaml`, `kubectl config view` → all blocked
3. **Real learner re-validation**: Recruit learner-H1 or new learner to independently complete Labs 2–4 with terminal

**Gate decision: LEARNER_KUBECTL_TERMINAL_READY**
