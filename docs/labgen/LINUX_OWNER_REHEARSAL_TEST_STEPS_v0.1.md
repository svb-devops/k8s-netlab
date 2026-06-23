# Linux Owner Rehearsal — Test Steps v0.1

**Date**: 2026-06-23  
**For**: Project Owner (rehearsal only — NOT for real trusted reader)  
**Lab**: Linux Files and Permissions Basics (`6c439064-4cad-4229-addb-36927128d565`)  
**Account**: `lnx-rehearsal-01` / password: `LinuxRehearsal@2026`  
**VM**: 401 (staging, home_lab_mvp profile)  
**Estimated time**: 15–25 minutes

> **Purpose**: Walk through the complete learner flow end-to-end, surface any friction or ambiguity, and confirm that the system behaves correctly before inviting a real trusted reader.

---

## A. Pre-Test Checklist

Before starting, confirm:

- [ ] Browser: Chrome or Firefox (recommended). Safari should also work.
- [ ] No existing active session on `lnx-rehearsal-01` — check [Session page](https://lab.cloudnetops.tech/app) if in doubt
- [ ] You are logged out, or in a private/incognito window to ensure a clean session
- [ ] The staging service is healthy: `curl -s https://lab.cloudnetops.tech/api/health` → `{"status":"healthy","proxmox":{"connected":true}}`
- [ ] VM 401 is running: `qm status 401` → `status: running`
- [ ] No operator monitoring needed for rehearsal, but keep a terminal open for post-run audit

**Estimated duration**: 15–25 minutes for first run

**If anything is broken before you start**: Check `journalctl -u k8s-netlab -p err --since "5 minutes ago" --no-pager` and contact operator.

---

## B. Entry Methods

Three ways to enter the Linux lab. Use whichever you want to test:

### B.1 Direct deep link (simplest — recommended for rehearsal)

```
https://lab.cloudnetops.tech/app?lab=6c439064-4cad-4229-addb-36927128d565
```

This link logs you in first (if not already), then takes you directly to the Linux lab detail page.

### B.2 Catalog route

1. Go to `https://lab.cloudnetops.tech/app`
2. Log in as `lnx-rehearsal-01` (password: `LinuxRehearsal@2026`)
3. You will see the experiment catalog — **6 labs total** (5 Kubernetes + 1 Linux)
4. Scroll to "Linux Files and Permissions Basics" and click it

### B.3 Mock article CTA

The article CTA is currently a deep link (not embedded in the article page — LOW-002, accepted limitation). For rehearsal, use the deep link from B.1.

---

## C. Lab Detail Page — What You Should See

After clicking the Linux lab (or following the deep link), you should land on the **Lab Detail** page.

**Expected content** — verify each item before clicking Start:

| Element | Expected |
|---------|----------|
| Title | "Linux Files and Permissions Basics" |
| Summary | One paragraph explaining the lab scope (create dir, write file, read file, chmod) |
| Background card | Blue card with ~3-sentence context about why Linux file permissions matter |
| Objectives | 4 items (file creation, reading, permissions, cleanup cycle) |
| Steps preview | 4 steps listed with titles and instruction summaries |
| "Start Lab" button | Visible and enabled |
| "Need help?" hint | Visible per step in preview (collapsible) |
| No `source_article_id` | Should NOT appear anywhere on page |
| No raw article text | Should NOT appear anywhere on page |

**Safety notice — confirm you do NOT see these prompts**:
- "sudo is required" — you should never need sudo
- "root access" — not required
- Any reference to real passwords, tokens, or keys
- Any reference to system directories (`/etc`, `/root`, `/var`, `/proc`)

If any of the above expected items are missing or safety notice items appear, **do not continue to real trusted reader** — record the issue and stop.

---

## D. Start Lab

1. Click **"Start Lab"** button
2. Wait for the session to initialize (typically 10–30 seconds)
3. You will be redirected to the **Session** page

**Expected session page state**:

| Element | Expected |
|---------|----------|
| Status indicator | LAB_ACTIVE |
| Environment type | Linux sandbox (NOT Kubernetes namespace) |
| Step 1 | Active and highlighted |
| Terminal / command input | Visible and accepting input |
| No kubeconfig | Should NOT appear |
| No kubectl commands | Should NOT appear in step instructions |
| "Need help?" | Collapsible hint visible for Step 1 |

**If Start fails**:

```
失败位置：Start Lab button click
截图：[attach screenshot]
错误码/提示：[copy exact error message]
当前步骤：Start
之前执行的命令：none
预期结果：LAB_ACTIVE session page
实际结果：[describe]
是否点过 Check：N/A
是否点过 Complete：N/A
```

Stop here. Do not retry. Report to operator.

---

## E. Step 1 — Create Directory and File

**Why**: Files and directories are the foundation of every Linux system. Creating a directory and writing a file inside your workspace is the first action any Linux user performs.

**Your commands** (run in order):

```bash
mkdir -p demo
printf 'hello labgen\n' > demo/message.txt
cat demo/message.txt
```

**Expected terminal output after `cat`**:

```
hello labgen
```

Click **"Check"** for Step 1.

**Expected Check result** — all 3 must pass:

| Check | Expected |
|-------|----------|
| `demo` directory exists | ✅ PASS |
| `demo/message.txt` file exists | ✅ PASS |
| `demo/message.txt` contains `hello labgen` | ✅ PASS |

**If Check fails**:

- "Permission denied" on mkdir → do NOT add sudo; contact operator
- File not found → re-run: `printf 'hello labgen\n' > demo/message.txt`
- Content mismatch → check for typos; re-run `printf 'hello labgen\n' > demo/message.txt`
- Check the "Need help?" hint for step-specific guidance

```
失败位置：Step 1 Check
截图：[attach]
错误码/提示：[copy]
当前步骤：Step 1
之前执行的命令：mkdir -p demo + printf ...
预期结果：3 checks PASS
实际结果：[describe which check failed]
是否点过 Check：Yes
是否点过 Complete：No
```

---

## F. Step 2 — Read the File

**Why**: Reading a file confirms its content without modifying it. `cat` simply copies the file to stdout. Understanding that cat only reads (not writes) is essential for correct permission reasoning.

**Your command**:

```bash
cat demo/message.txt
```

**Expected terminal output**:

```
hello labgen
```

Click **"Check"** for Step 2.

**Expected Check result**:

| Check | Expected |
|-------|----------|
| `demo/message.txt` content is `hello labgen` | ✅ PASS |

**If Check fails**:

- If cat shows "No such file or directory" → return to Step 1 and re-run both commands
- If content differs → recreate with: `printf 'hello labgen\n' > demo/message.txt`
- Do NOT use sudo at any point

---

## G. Step 3 — Set File Permissions

**Why**: File permissions control who can read, write, or execute a file. Setting a file to `600` (owner read+write only) is the standard for private files.

**Your commands**:

```bash
chmod 600 demo/message.txt
stat -c "%a" demo/message.txt
```

**Expected terminal output after `stat`**:

```
600
```

Click **"Check"** for Step 3.

**Expected Check result**:

| Check | Expected |
|-------|----------|
| `demo/message.txt` file mode is `600` | ✅ PASS |

**If Check fails**:

- If stat shows "No such file or directory" → file was deleted; return to Step 1
- If stat shows wrong number (e.g. `644`) → re-run: `chmod 600 demo/message.txt`
- chmod does NOT require sudo for files you own

---

## H. Step 4 — Complete the Lab

**Why**: Lab resources run in a temporary sandbox. When you complete the lab, the system automatically removes the workspace directory and all session resources. Understanding this cycle reinforces the sandbox safety contract.

**No commands to run in Step 4.**

Verify:

- [ ] Steps 1, 2, 3 all show green pass indicator
- [ ] "Complete Lab" button is enabled (not greyed out)

Click **"Complete Lab"**.

**Expected result**:

| Element | Expected |
|---------|----------|
| Session state | LAB_CLOSED |
| Page shows completion confirmation | Yes |
| Workspace files automatically deleted | Yes (no manual cleanup needed) |
| cleanup_verified | True |

**If Complete fails**:

- If "Complete Lab" button is greyed out → click Check on each earlier step to confirm all pass
- If Complete button returns error → do NOT click again repeatedly; record error and report

```
失败位置：Step 4 Complete
截图：[attach]
错误码/提示：[copy]
当前步骤：Step 4
之前执行的命令：none (completion step)
预期结果：LAB_CLOSED, workspace cleaned up
实际结果：[describe]
是否点过 Check：[yes, which steps]
是否点过 Complete：Yes
```

---

## I. Post-Completion — Owner Feedback Form

After completing the lab, answer these questions honestly. This is your rehearsal feedback — identify any friction before the real reader experiences it.

**Q1**: Was the entry point (deep link or catalog) clear? `(clear / ok / unclear)`  
**Q2**: Did the Background card explain *why* this lab exists? `(clear / ok / unclear)`  
**Q3**: Were the commands in each step unambiguous? `(easy / ok / difficult — note which step if difficult)`  
**Q4**: Did the expected output in each step help you confirm you were on track? `(yes / partially / no)`  
**Q5**: Was the "Need help?" hint useful when visible? `(yes / didn't need it / no)`  
**Q6**: Which step was hardest? `(Step 1 / 2 / 3 / 4 / none)`  
**Q7**: Did you need any help from the operator? `(no / yes — describe)`  
**Q8**: After completing, do you understand what you just practiced? `(yes / partially / no)`  
**Q9**: If you were a real reader, could you have completed this independently? `(yes / with minor issues / no)`  
**Q10**: Open suggestions — anything unclear, broken, or confusing?  

---

## J. Post-Run Audit (Operator Runs This After You Click Complete)

After you click Complete, tell the operator to run:

```bash
# Check session state
python3 -c "
import json
with open('/root/k8s-netlab/data/sessions.json') as f:
    d = json.load(f)
# Find most recent linux session for lnx-rehearsal-01
for sid, s in sorted(d.items(), key=lambda x: x[1].get('started_at',''), reverse=True):
    if 'linux' in str(s.get('lab_id','')) or s.get('target_domain') == 'linux':
        print('Session:', sid[:8], '| state:', s.get('state'), '| cleanup_verified:', s.get('cleanup_verified'), '| residual:', s.get('residual'))
        break
"

# Check active sessions
python3 -c "
import json
with open('/root/k8s-netlab/data/sessions.json') as f:
    d = json.load(f)
active = [s for s in d.values() if s.get('state') not in (None,'LAB_CLOSED','LAB_ABORTED','LAB_CLEANUP_FAILED')]
print('Active sessions:', len(active))
"

# Check tainted VMs
cat /root/k8s-netlab/data/tainted_vms.json

# Check catalog
curl -s https://lab.cloudnetops.tech/api/health

# Check error logs
journalctl -u k8s-netlab -p err --since "30 minutes ago" --no-pager | tail -20

# K8s Lab 5 still accessible?
# (requires auth — check via data file)
python3 -c "
import json
with open('/root/k8s-netlab/data/lab_drafts.json') as f:
    d = json.load(f)
k5 = next((v for k,v in d.items() if 'cf019133' in k), None)
print('K8s Lab 5:', k5.get('publish_status') if k5 else 'NOT FOUND')
"

# VMID 500-599 untouched?
python3 -c "
import json
with open('/root/k8s-netlab/data/sessions.json') as f:
    d = json.load(f)
prod = [s.get('vm_id') for s in d.values() if s.get('vm_id') and 500 <= int(str(s.get('vm_id')).split('.')[0]) <= 599]
print('VMID 500-599 in sessions:', prod)
"
```

**Expected audit results** (all must pass before proceeding to real reader):

| Check | Expected |
|-------|----------|
| Session state | LAB_CLOSED |
| cleanup_verified | True |
| residual | 0 (or absent) |
| Active sessions | 0 |
| Tainted VMs | `{}` |
| Health | `{"status":"healthy","proxmox":{"connected":true}}` |
| K8s Lab 5 | published |
| VMID 500-599 | `[]` (empty) |
| Error logs | No new exceptions |

---

## K. Failure Report Template

If any step fails, copy and fill this template:

```
失败位置：[Step X / Start / Complete / Login / Catalog]
截图：[attach or describe]
错误码/提示：[exact text]
当前步骤：[which step you were on]
之前执行的命令：[exact commands]
预期结果：[what should have happened]
实际结果：[what actually happened]
是否点过 Check：[yes/no, which steps]
是否点过 Complete：[yes/no]
浏览器控制台报错：[F12 → Console, copy any red errors]
```

---

## L. After Rehearsal — Decision

After completing the full flow and post-run audit:

**If ALL steps passed and feedback shows no blockers**:
→ Tell the operator: "Owner rehearsal PASSED. Ready to invite real trusted reader."
→ Operator will ask you to confirm: YES / NO + reader identity + time window

**If ANY step failed or feedback shows significant confusion**:
→ Tell the operator what failed and which step
→ Operator will fix the issue and run another rehearsal round before involving a real reader

**The real trusted reader pilot will NOT start until you confirm rehearsal passed.**
