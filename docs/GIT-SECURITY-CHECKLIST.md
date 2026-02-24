# Git Commit Security Checklist

**Mandatory read — enforced security checks before every Git commit**

---

## Core Principles

> ⚠️ Never commit sensitive information to Git
> ⚠️ Everything pushed to GitHub is public
> ⚠️ Git history is permanent and hard to clean
> ⚠️ These checks are mandatory, not optional

---

## Sensitive Information Categories

### 🔴 Absolute Prohibition (must remove before commit)

| Category | Examples |
|----------|---------|
| Passwords | `password="abc123"`, `passwd=...` |
| API keys / Tokens | `api_key="sk-..."`, `token="..."` |
| Private keys | `*.key`, `*.pem`, `*.p12` |
| Database credentials | `mysql://user:pass@host/db` |
| SSH private keys | `-----BEGIN RSA PRIVATE KEY-----` |
| Real host IPs | Actual server / infrastructure IPs |
| Real network topology | Diagrams containing real addresses |
| `.env` files | Any file with live credentials |
| User data | `users.json`, `*.sqlite`, `*.db` |
| Internal hostnames | Hostnames that reveal infrastructure |

### 🟡 Must Sanitize (replace with placeholders)

| Original | Placeholder |
|----------|-------------|
| Real host IP | `<HOST_IP>` |
| Gateway IP | `<GATEWAY_IP>` |
| VM IP | `<VM_IP>` |
| Admin username | `<USERNAME>` |
| Domain | `your-domain.com` / `example.com` |
| Port in context | `<PORT>` |
| Network range | `<NETWORK>/24` or `10.0.0.0/24 (example)` |

---

## Pre-Commit Checklist

### Phase 1 — Automated Scan (run the script)

```bash
bash scripts/pre-commit-security-check.sh
```

All 8 checks must pass before proceeding.

### Phase 2 — Manual Review (3 minutes)

- [ ] **Commit message** — no real IPs, no real usernames, no specific config details
- [ ] **Documentation** — network diagrams use placeholder values, example annotations present
- [ ] **Code comments** — no real config in inline comments or TODOs
- [ ] **Test data** — test files use synthetic data, no real user info
- [ ] **Screenshots** — any images blurred or cropped if they contain real addresses

### Phase 3 — Pre-Push Verification (Automated)

**This phase is now fully automated.** The `pre-push` Git hook runs on every
`git push` and scans all commits being pushed.

```
git push
  ↓
pre-push hook triggers automatically
  ↓
bash scripts/pre-push-security-check.sh
  ↓
✅ All checks pass → push proceeds
❌ Issue found    → push rejected with details
```

Manual trigger (to test without pushing):

```bash
# Check the last 2 commits manually
bash scripts/pre-push-security-check.sh HEAD~2 HEAD
```

**Hook not installed?** Run the installer:

```bash
bash scripts/install-git-hooks.sh
```

---

## Sanitization Guide

### IP Addresses

```
# Before (example of what NOT to commit)
访问 http://192.0.2.10:8000
PVE 宿主机 (192.0.2.10)

# After
访问 http://<HOST_IP>:8000
PVE 宿主机 (<HOST_IP>)
```

> Note: `192.0.2.x` is an RFC 5737 documentation address used here for
> illustration only — replace every occurrence with your actual value.

### Network Topology

```
# Before (example of what NOT to commit)
Router (192.0.2.1)
  +-- Host (192.0.2.10)

# After
Router (<GATEWAY_IP>)
  +-- Host (<HOST_IP>)
```

### Passwords

```python
# Before  ❌
password = "MyRealPassword123"

# After   ✅
password = os.getenv("PASSWORD")
```

### SSH Commands

```
# Before (example of what NOT to commit)
ssh root@192.0.2.10

# After
ssh <USER>@<HOST_IP>
```

### Config Files

```bash
# ✅ Commit this (template with placeholders):
cp config.yml config.example.yml
# edit config.example.yml to use <HOST_IP>, <PASSWORD>, etc.
git add config.example.yml

# ❌ Never commit the live config:
# echo "config.yml" >> .gitignore
```

---

## Emergency Response — If Sensitive Data Was Already Pushed

### Committed but not yet pushed

```bash
# Undo the last commit (keeps changes locally)
git reset HEAD~1
# Fix the sensitive file, then recommit
```

### Already pushed to GitHub

```bash
# Step 1: Immediately rotate ALL exposed credentials
#   - Change passwords
#   - Revoke and regenerate API keys
#   - Notify relevant parties

# Step 2: Remove from history with git-filter-repo (preferred)
pip install git-filter-repo
git filter-repo --path path/to/sensitive/file --invert-paths

# Or use BFG Repo-Cleaner:
# java -jar bfg.jar --delete-files sensitive-file.txt

# Step 3: Force push (coordinate with all collaborators first)
git push origin --force --all
git push origin --force --tags

# Step 4: Ask collaborators to re-clone (their local copies still have history)
```

> ⚠️ Assume any exposed credential is compromised the moment it hits GitHub.
> Rotate first, clean history second.

---

## .gitignore Reference

Ensure the following are excluded in your `.gitignore`:

```gitignore
# Credentials and secrets
.env
.env.*
*.key
*.pem
*.p12
config/secrets.*
proxmox_credentials.*

# Runtime data (may contain real IPs in logs)
logs/
data/
*.log
*.sqlite
*.db

# OS / editor
.DS_Store
Thumbs.db
.vscode/
```

---

## Project-Specific Setup

To configure real IP detection for this project, create a local
**non-committed** file `.security-config` (already in `.gitignore`):

```bash
# .security-config — DO NOT COMMIT THIS FILE
# Fill in your actual values:
export REAL_HOST_IP="<your-pve-host-ip>"
export REAL_NETWORK="<your-home-network-cidr>"
export REAL_GATEWAY="<your-gateway-ip>"
```

Then `scripts/pre-commit-security-check.sh` will use these values
for project-specific IP detection.

---

## Best Practices Summary

1. **Use environment variables** for all secrets and host-specific values
2. **Provide `.example` templates** for every config file
3. **Annotate examples** — add `# example` or `(example)` comments near placeholder values
4. **Install the Git hook** once per clone: `bash scripts/install-git-hooks.sh`
5. **Never use `--no-verify`** to bypass checks
6. **Rotate credentials immediately** if anything is accidentally exposed

---

## Compliance

This checklist aligns with:
- [GitHub Secret Scanning](https://docs.github.com/en/code-security/secret-scanning)
- OWASP Sensitive Data Exposure prevention
- CIS Critical Security Control 3: Data Protection

---

---

## Automated Protection — Dual-Layer Hooks

As of 2026-02-23, both Git hooks are installed and active:

| Hook | Trigger | Checks | Defense against |
|------|---------|--------|-----------------|
| `pre-commit` | `git commit` | Staged changes (8 checks) | Committing secrets |
| `pre-push` | `git push` | All pushed commits (8 checks) | Pushing with `--no-verify` |

### For new team members

```bash
git clone <repo>
cd k8s-netlab
bash scripts/install-git-hooks.sh   # installs both hooks
```

### Hook flow

```
git commit          git push
     ↓                   ↓
pre-commit hook     pre-push hook
     ↓                   ↓
8-point scan        8-point scan
     ↓                   ↓
✅ pass → ok        ✅ pass → ok
❌ fail → blocked   ❌ fail → blocked
```

### Emergency bypass (strongly discouraged)

```bash
git push --no-verify   # bypasses pre-push only
                       # must audit and fix immediately after
```

---

*Version: 1.1 — 2026-02-23 | Mandatory for all contributors*
