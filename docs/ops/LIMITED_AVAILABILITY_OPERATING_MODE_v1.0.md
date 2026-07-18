# Limited-Availability Operating Mode v1.0

## 状态

`documentation_only` —— 本文档记录当前宿主机非 24×7 运行条件下的实际运维行为，不改变任何已发布内容/公开访问范围。Phase 1《Kubernetes 高频故障排查实战系列》完全保持已发布状态，本轮只处理可靠性与调度基础设施。

## 背景

当前生产宿主机（`pve`）不是 24×7 运行，每天约开机 8 小时。这意味着：

- 任何依赖固定时刻触发的 cron/systemd timer，如果计划时间落在宿主机关机窗口内，**不会自动补跑**——除非显式启用了 `Persistent=true`（systemd timer）或类似机制。
- 关机前必须确认没有学员正在进行中的实验会话（`active_sessions=0`），否则会中断真实使用者的实验。
- 开机后需要按固定清单核对几项健康状态，而不是假设"服务起来了就没问题"。

## 关键数据持久化任务的调度方式

只有以下两个任务从 cron 迁移到了 systemd service + timer（`Persistent=true`）；其余 cron 任务（`backup-data.sh`、`cleanup-orphan-vms.sh`、`stability_watch.sh`、`labgen_expire_sessions_cron.sh`）本轮未改动，继续沿用原有 cron 行为。

| 任务 | 旧方式 | 新方式 | 频率 |
|------|--------|--------|------|
| 全量一致性备份（data JSON + Directus Postgres/uploads/extensions） | cron `30 3 * * *` | `k8s-netlab-backup-full-state.timer` | 每天 03:30 |
| DataRetentionService 清理（zombie drafts / orphaned review diffs / 审计日志轮转） | 从未自动调度，历史上全靠人工偶尔手动跑 | `k8s-netlab-data-retention.timer` | 每周日 04:00 |

两个 timer 单元文件在仓库内维护于 `deploy/systemd/`，生产环境安装于 `/etc/systemd/system/`（两处需保持同步，改动 `deploy/systemd/*.service`/`*.timer` 后必须手动 `cp` 到 `/etc/systemd/system/` + `systemctl daemon-reload`，本仓库未做自动同步）。

### 为什么用 `Persistent=true` 而不是缩短检查周期

`Persistent=true` 让 systemd 记录每个 timer 上次实际触发的时间；如果宿主机在计划触发时刻是关机状态，下次开机后 systemd 会立即补跑一次错过的任务，而不是安静地等到下一个自然触发时刻。这正是"非 24×7 主机"场景下唯一正确的调度方式——不能靠更频繁的检查来弥补，因为如果宿主机压根没开机，再频繁的检查也不会执行。

已用一次性 scratch timer（`OnCalendar=*-*-* *:*:00`）实测验证：`systemctl stop` 跨越一个计划触发分钟后 `systemctl start`，任务在重启后几秒内立即补跑，而不是等到下一个整分钟——这正是 `Persistent=true` 在真实"宿主机关机跨过计划时刻"场景下的行为。

### flock 互斥

`backup-full-state.sh` 内部已有自己的非阻塞 `flock`（`/var/lock/k8s-netlab-backup-full-state.lock`），systemd service 本身不需要重复加锁。`run-data-retention-cron.sh`（DataRetentionService 的调度包装脚本）同样用非阻塞 `flock`（`/var/lock/k8s-netlab-data-retention.lock`）——已实测：故意让另一个进程持有该锁时，脚本立即以 `exit 1` 退出并打印 FATAL 日志，不会等待、不会并发执行。

## 如何查看最近一次成功备份

```bash
ls -t /root/backups/k8s-netlab-full/ | head -1
cat /root/backups/k8s-netlab-full/<最新目录>/manifest.json | python3 -m json.tool
```

`manifest.json` 里的 `files[].sha256` 是备份产出时计算的校验和；如果需要重新核对某次备份是否完好（比如怀疑磁盘有问题），可以独立重算：

```bash
cd /root/backups/k8s-netlab-full/<日期目录>
python3 -c "
import json, hashlib
m = json.load(open('manifest.json'))
for e in m['files']:
    h = hashlib.sha256(open(e['filename'],'rb').read()).hexdigest()
    print('OK ' if h == e['sha256'] else 'MISMATCH ', e['filename'])
"
```

也可以直接看 systemd 记录的执行结果，不需要进容器/翻日志文件：

```bash
systemctl status k8s-netlab-backup-full-state.service    # 上次执行是否成功
journalctl -u k8s-netlab-backup-full-state.service -n 50 --no-pager
systemctl list-timers k8s-netlab-backup-full-state.timer  # 下次/上次触发时间
```

## 如何查看最近一次 DataRetentionService 运行结果

```bash
systemctl status k8s-netlab-data-retention.service
journalctl -u k8s-netlab-data-retention.service -n 50 --no-pager
```

日志里会打印 archive 前后的对比（`lab_drafts`/`lab_review_diffs`/`llm_audit_log`/`lab_runtime_audit` 各自的 total/eligible/archived 计数），以及归档产物路径（`data/archive/*.json`）。也可以手动跑一次 dry-run 立即查看当前状态而不等下周日：

```bash
cd /root/k8s-netlab && source venv/bin/activate
python3 scripts/run_data_retention.py          # dry-run，不改数据
python3 scripts/run_data_retention.py --execute  # 真正归档
```

## 开机后必须检查的 health 项

```bash
curl -s https://lab.cloudnetops.tech/api/health | python3 -m json.tool
```

必须确认：

- `status == "healthy"`
- `sessions.tainted_vm_count == 0`（若非 0，参考 `RUNBOOK.md` 场景七排查残留 taint）
- `sessions.failed_terminal_session_count == 0`（若非 0，说明有 session 卡在 `LAB_START_FAILED`/`LAB_CLEANUP_FAILED`，需要人工核实是否真实资源残留还是误判）
- `session_ttl_minutes == 90`（若不是，说明 `.env` 或 `/etc/labgen/home_lab_mvp.env` 出现了同名变量覆盖漂移——见 2026-07-18 的 CHANGELOG 事故记录，`scripts/ops_smoke_check.sh` 的检查项 11 会自动捕获这类漂移）

```bash
journalctl -u k8s-netlab -p err --since "10 minutes ago" --no-pager   # 开机/重启后无新增错误
bash scripts/ops_smoke_check.sh                                       # 完整的关键配置核对清单
```

## 关机前必须确认的事项

**任何时候，只要还有学员在做实验，不得直接关机。**

```bash
curl -s https://lab.cloudnetops.tech/api/health | python3 -c "
import sys, json
d = json.load(sys.stdin)['sessions']
print('active_session_count:', d['active_session_count'])
"
```

`active_session_count` 必须为 `0` 才能安全关机。如果非 0，说明至少有一个 session 处于 `LAB_ACTIVE`（学员正在终端里操作），此时关机会直接掐断该学员的连接，且该 session 大概率会被 `LABGEN_LAB_SESSION_TTL_MINUTES`（90 分钟）超时机制或 abort 清理流程标记为异常结束——不是数据丢失风险，但是明确的用户体验破坏，应避免。

## 当前运营边界（重申）

- 当前处于"内容已完整可用、但未做任何主动引流/推广"的状态——系列六篇文章/实验对任何已注册用户都是可访问的，只是没有主动 Growth 动作
- 本文档不决定公开站点的每日具体开放时段——开放时段由 Owner 后续另行决定；本文档只保证"不管站点在哪个时间窗口开放，关键数据不会因为宿主机不是 24×7 而丢失或产生误判失败"

## 相关文档

- `docs/labgen/PHASE1_KUBERNETES_SERIES_CLOSURE_v1.0.md` —— Phase 1 系列收官报告
- `docs/ops/DIRECTUS_BACKUP_RESTORE_RUNBOOK.md` —— 备份产物的详细恢复流程（本文档只讲调度/查看，不讲恢复步骤）
- `RUNBOOK.md` —— 场景化运维手册（含场景七 LAB_CLEANUP_FAILED/tainted VM 人工恢复流程）
