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
