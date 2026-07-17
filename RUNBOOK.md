# Runbook — K8S NetLab

生产事故处理手册。出问题时按步骤执行，不要靠记忆。

---

## 快速参考

| 操作 | 命令 |
|------|------|
| 查服务状态 | `systemctl status k8s-netlab` |
| 重启服务 | `systemctl restart k8s-netlab` |
| 查实时日志 | `journalctl -u k8s-netlab -f` |
| 查错误日志 | `journalctl -u k8s-netlab -p err --since "1 hour ago"` |
| 健康检查 | `curl -s https://lab.cloudnetops.tech/api/health` |
| 查备份 | `ls /root/backups/k8s-netlab/` |

---

## 场景一：服务不响应 / UptimeRobot 告警

```bash
# 1. 确认服务状态
systemctl status k8s-netlab

# 2. 查最近错误
journalctl -u k8s-netlab -p err --since "30 minutes ago" --no-pager

# 3a. 如果进程已崩溃 → 直接重启
systemctl restart k8s-netlab
sleep 3
curl -s https://lab.cloudnetops.tech/api/health

# 3b. 如果进程存活但不响应 → 强制重启
systemctl kill k8s-netlab
systemctl start k8s-netlab
```

---

## 场景二：回滚到上一个版本

```bash
# 1. 确认当前版本
git -C /root/k8s-netlab log --oneline -5

# 2. 找到要回滚的 commit（上一个正常版本）
git -C /root/k8s-netlab log --oneline -20

# 3. 回滚代码（用 revert 保留历史，不用 reset）
git -C /root/k8s-netlab revert <bad-commit-hash> --no-edit

# 4. 重启服务
systemctl restart k8s-netlab
sleep 3
curl -s https://lab.cloudnetops.tech/api/health

# 5. 推送回滚 commit
git -C /root/k8s-netlab push
```

> **不要用 `git reset --hard`**，会丢失 commit 历史，排查困难。

---

## 场景三：数据文件损坏

```bash
# 1. 查看可用备份
ls -lt /root/backups/k8s-netlab/

# 2. 停服务（防止正在写入）
systemctl stop k8s-netlab

# 3. 恢复备份（替换为最近日期）
cp /root/backups/k8s-netlab/<最近日期>/*.json /root/k8s-netlab/data/

# 4. 启动服务
systemctl start k8s-netlab
curl -s https://lab.cloudnetops.tech/api/health
```

---

## 场景四：VM 创建失败（用户报障）

```bash
# 1. 确认模板 VM 在池中
pvesh get /pools/k8s-netlab

# 如果模板不在池里（最常见根因）：
pvesh set /pools/k8s-netlab --vms 100

# 2. 确认 Token 权限
pvesh get /access/acl | grep k8s-netlab

# 3. 手动测试克隆
bash /root/k8s-netlab/scripts/test-template.sh
```

---

## 日志查阅习惯

每次发布后检查一次：

```bash
journalctl -u k8s-netlab -p warning --since "1 hour ago" --no-pager
```

有 `ERROR` 或 `WARNING` 出现时，判断是否需要处理，不要忽略。

---

## 环境变量加载顺序（单一真相来源）

系统使用两层 env 文件，由 `backend/labgen/ops_env.py` 统一管理：

| 层级 | 文件 | 说明 |
|------|------|------|
| 基础层 | `/root/k8s-netlab/.env` | 通用配置，检入版控（不含密钥） |
| 覆盖层 | `/etc/labgen/home_lab_mvp.env` | 生产密钥和路径（不检入版控，仅存在于宿主机） |

加载顺序：`.env` 先，`home_lab_mvp.env` 后（`override=True`）。覆盖层的值优先。

`ops_env.py` 中的 `load_ops_env()` 函数封装此逻辑，所有脚本必须通过它加载，不得直接调用 `python-dotenv`：

```python
from backend.labgen.ops_env import load_ops_env
load_ops_env()  # 自动加载两层，正确顺序
```

---

## VMID 分配策略

| 范围 | 用途 | 策略 |
|------|------|------|
| 101 | 模板 VM | 绝对不删除，必须在 k8s-netlab pool 中 |
| 200–499 | staging / internal / rehearsal | 手动或脚本管理 |
| 500–599 | **生产学员运行时**（runtime allocator 自动分配） | Claude Code / 人工禁止手动触碰 |
| 299 | K3s rehearsal/staging platform VM | exempt 保护，不受自动清理影响 |
| 400–401 | staging/owner-test VM | exempt 保护（参见 VM_CLEANUP_EXEMPT_IDS） |

**硬规则**：
- `qm delete` / `qm destroy` 前必须 `qm config <id>` 确认归属
- VMID 500–599 只允许 runtime allocator 创建，禁止手动分配
- 任何网络变更后运行 `bash /root/scripts/verify-all-bridges.sh`

---

## K3s v1.34.4 已知限制（workaround 已到位）

| 问题 | 症状 | Workaround |
|------|------|------------|
| RBAC informer 缓存破坏 | ClusterRole UPDATE (PUT) 后 SA token 403 Forbidden | 改为 delete + create（DELETE+ADD 事件对）|
| Storage index by-name 不可靠 | `kubectl get <resource> <name>` 有时返回空 | 用 python kubernetes client list+filter |
| TokenRequest 短有效期 | K3s 将 SA token 缩短至 ~3-5min | 每次 step check 前 reprovision verifier credentials |
| local registry 要求 | 公网不可达 → ImagePullBackOff | Lab image 必须使用 `172.16.100.1:5000/library/` 前缀 |
| `describe service` 的 Endpoints 字段永久 `<none>` | `kubectl get endpoints <svc>` 正确显示已填充的 IP，但同一时刻 `kubectl describe service <svc>` 的 "Endpoints:" 行永远显示 `<none>`（实测持续 20s+ 不自愈，`Selector:`/`Type:` 等其它字段正常），与 v1 Endpoints 已废弃、kubectl 内部改走 EndpointSlice 聚合但该聚合路径在此 K3s 版本下失效有关 | Lab 内容/排障文档里验证 Endpoints 是否填充只能用 `kubectl get endpoints`，不能依赖 `describe service` 输出里的 Endpoints 行（Selector 行本身仍可靠，只是 Endpoints 聚合行不可靠）——2026-07-12 生产第二个 lab（Service-no-Endpoints）rehearsal 时发现 |

---

## 场景七：Failed Lab Session 恢复

**症状**：`GET /api/lab-sessions/admin/failed` 返回非空列表。

```bash
# 1. 列出所有失败 session
ADMIN_TOKEN=$(grep ADMIN_TOKEN /root/k8s-netlab/.env | cut -d= -f2)
# 通过 admin 账号登录，然后调用：
# POST /api/lab-sessions/admin/{session_id}/force-close
# {"audit_note": "<描述原因>", "residual_risk": false}

# 2. 调查 namespace 是否还存在（K3s VM 上）
# ssh 进对应 VM 后：
# kubectl get ns | grep "lab-<session_id>"

# 3. 若 namespace 不存在或 VM 已销毁 → residual_risk=false
# 若 namespace 存在且无法删除 → residual_risk=true

# 4. 执行 force-close（通过 API 或 service 层）：
cd /root/k8s-netlab && source venv/bin/activate
python3 -c "
from backend.labgen.lab_session_repository import LabSessionRepository
from backend.labgen.models import LabSessionStatus
from datetime import datetime, timezone
repo = LabSessionRepository()
session = repo.get('<SESSION_ID>')
session.lab_session_status = LabSessionStatus.LAB_FORCE_CLOSED
session.admin_audit_note = '<YOUR_AUDIT_NOTE>'
session.admin_force_closed_with_residual_risk = False
session.cleanup_verified = True
repo.update(session)
"
```

---

## 场景八：数据文件清理和归档

```bash
# 1. 运行报告（只读）
cd /root/k8s-netlab && source venv/bin/activate
python3 -c "
import json
from backend.labgen.data_retention import DataRetentionService
svc = DataRetentionService()
print(json.dumps(vars(svc.report()), indent=2, default=list))
"

# 2. 试运行（不修改文件）
python3 -c "
from backend.labgen.data_retention import DataRetentionService
svc = DataRetentionService()
result = svc.run(dry_run=True)
print(f'Orphaned diffs to archive: {result.lab_review_diffs_archived}')
print(f'Audit entries to rotate: {result.llm_audit_entries_archived + result.lab_runtime_entries_archived}')
"

# 3. 执行清理（先备份！）
cp data/lab_review_diffs.json data/lab_review_diffs.json.bak
python3 -c "
from backend.labgen.data_retention import DataRetentionService
svc = DataRetentionService()
result = svc.run(dry_run=False)
print(f'Archived to: {result.archive_paths}')
"
```

归档文件存放在 `data/archive/`，不自动删除。定期检查磁盘空间。

---

## 场景九：Directus PostgreSQL / uploads / extensions 备份与恢复

详见 [docs/ops/DIRECTUS_BACKUP_RESTORE_RUNBOOK.md](docs/ops/DIRECTUS_BACKUP_RESTORE_RUNBOOK.md)。

快速参考：
```bash
# 手工执行一次全量备份（data/*.json + Directus postgres + uploads + extensions）
bash /root/k8s-netlab/scripts/backup-full-state.sh

# 查看最近备份
ls -la /root/backups/k8s-netlab-full/ | tail -10
```

每日 03:30 自动执行（crontab），与原有 03:00 的 `backup-data.sh` 错开。当前
**未配置异地备份**（`OFFSITE_BACKUP_NOT_CONFIGURED`），本地备份与生产数据同处一台
物理机，不构成灾难恢复能力，需 owner 决策异地备份目标。

---

## Owner Internal Run Checklist

执行 Owner 内部运行前必须全部通过：

- [ ] `curl -s https://lab.cloudnetops.tech/api/health` → `{"status":"healthy"}`
- [ ] `/api/lab-sessions/admin/failed` 返回空列表
- [ ] `tainted_vms.json` 为空 `{}`
- [ ] 所有 lab sessions `cleanup_verified=True`
- [ ] Owner Article #1 (`crashloopbackoff-describe-logs`) 已 published
- [ ] CTA `/api/articles/crashloopbackoff-describe-logs/lab-cta` → `has_cta=true`
- [ ] Lab draft `bb4fe651` publish_status=published，step-1 使用本地 registry
- [ ] VM 299 verifier credentials present（health 端点确认）
- [ ] `python3 scripts/provision_verifier_credentials.py --vm-id 299 --dry-run` → 无错误
- [ ] `mypy backend/ --ignore-missing-imports` → 0 errors
- [ ] `pytest tests/ -x -q` → 全部通过，coverage ≥ 90%

---

## Small Cohort Readiness Checklist

Owner Internal Run Checklist 全部通过，且：

- [ ] Zero Technical Debt Gate 已通过（mypy/recovery/retention/runbook/health/e2e）
- [ ] 无 LAB_CLEANUP_FAILED 或 LAB_START_FAILED 待处理 session
- [ ] `data/lab_review_diffs.json` 大小 < 1MB
- [ ] 生产 VMID 500-599 中无遗留 VM（`qm list | grep -E "5[0-9][0-9]"` 为空）
- [ ] Codex review 通过（`codex review --base main` 无 BLOCKER）
- [ ] safety-reviewer 通过（最近 A/B 类变更已审查）
- [ ] 服务 uptime > 24h（`systemctl status k8s-netlab` 查看 Active 时间）

---

## 场景五：smoke-admin 密码丢失

smoke-admin 是 LabGen 管理后台的内置管理员账号（由 `ADMIN_USERNAMES=smoke-admin` 控制）。

**重置密码（不需要知道旧密码）：**

```bash
cd /root/k8s-netlab
source venv/bin/activate
python3 scripts/reset_admin_password.py --username smoke-admin
```

新密码会写入 `/root/.k8s-netlab-admin-credentials`（chmod 600，仅 root 可读），**不会打印到终端**。

**查看当前存储的密码：**

```bash
cat /root/.k8s-netlab-admin-credentials
```

**验证密码有效（不执行重置）：**

```bash
python3 scripts/reset_admin_password.py --username smoke-admin --verify-only
```

**安全约束：**
- 密码仅存储在 `/root/.k8s-netlab-admin-credentials`，不写入代码或日志
- 发版前验证 `--verify-only` 通过
- 如旧密码文件丢失，直接重新运行重置脚本即可（无需旧密码）

---

## 场景六：Verifier Credentials 丢失或路径错误

**症状**：学员创建 lab session 失败，日志报 `verifier credentials not found`。

**正确的 credential 路径**：`/var/lib/labgen-staging/verifier-credentials/<vm_id>/`

**重新 provision（以 VM 299 为例）：**

```bash
cd /root/k8s-netlab
source venv/bin/activate
python3 scripts/provision_verifier_credentials.py --vm-id 299
```

脚本会自动加载 `.env` + `/etc/labgen/home_lab_mvp.env`，写入正确路径。

**验证：**

```bash
ls -la /var/lib/labgen-staging/verifier-credentials/299/
```

**关键约束**：
- 不要在没有加载 `home_lab_mvp.env` 的情况下手动调用 Python 临时脚本
- 永远不要使用相对路径 `creds/vm_creds/` 作为生产路径
- 使用 `scripts/provision_verifier_credentials.py`，它内置了路径安全校验

---

## 自动化配置验证脚本

快速验证关键配置和运行时状态，全部通过再进行任何操作：

```bash
bash /root/k8s-netlab/scripts/ops_smoke_check.sh
```

脚本检查项：
1. 服务健康端点（`/api/health` = healthy）
2. 环境文件存在（`.env` + `/etc/labgen/home_lab_mvp.env`）
3. Verifier credentials 存在（VM 299 路径）
4. 模板 VM 101 在 k8s-netlab pool 中
5. VMID 500-599 无遗留 VM
6. 无失败 session（failed endpoint = 空）
7. `tainted_vms.json` 为空 `{}`
8. `lab_review_diffs.json` 大小 < 1MB
9. Cloudflare Tunnel 存活（cloudflared 进程）
10. `mypy backend/` 0 errors
