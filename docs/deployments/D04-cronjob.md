# 案例 D04: CronJob 定时任务系统

## 📚 案例信息

- **难度**: ⭐⭐⭐（中级）
- **时长**: 30 分钟
- **环境**: K3s 单节点集群
- **前置**: 了解 Pod 基础概念

## 🎯 你将完成什么

用 K8s `CronJob` 创建定时任务系统，包含：

- 每分钟执行一次的定时任务（生成时间戳日志）
- 控制保留历史 Job 数量（`successfulJobsHistoryLimit`）
- 触发手动执行（从 CronJob 创建一次性 Job）
- 处理任务执行超时（`activeDeadlineSeconds`）

学完本案例，你将理解：
1. CronJob → Job → Pod 的三层关系
2. Cron 表达式在 K8s 中的格式和限制（最小粒度 1 分钟）
3. 如何查看历史 Job 的执行日志
4. `concurrencyPolicy` 防止任务积压的作用

## 🏗️ 架构图

```
CronJob（每分钟触发）
    │
    ├──▶ Job（第 1 次）──▶ Pod（执行完成 → Completed）
    ├──▶ Job（第 2 次）──▶ Pod（执行完成 → Completed）
    └──▶ Job（第 3 次）──▶ Pod（执行中...）

保留规则：成功保留最近 3 个 Job，失败保留最近 1 个 Job
```

## 🐳 使用的镜像

| 镜像 | 用途 | 来源 |
|------|------|------|
| `busybox:1.28` | 执行 shell 脚本（date、echo、sleep） | 本地 registry mirror |

## ⚠️ 开始前

确认集群就绪：

```bash
kubectl wait --for=condition=Ready node --all --timeout=120s
kubectl get node
```

---

## 🔬 步骤

### Step 1: 创建基础 CronJob

**目标**：每分钟打印一次当前时间戳和节点信息。

```bash
kubectl apply -f - <<'EOF'
apiVersion: batch/v1
kind: CronJob
metadata:
  name: report-job
spec:
  schedule: "*/1 * * * *"      # 每分钟执行一次
  concurrencyPolicy: Forbid    # 上一个 Job 未完成时跳过本次
  successfulJobsHistoryLimit: 3  # 保留最近 3 次成功记录
  failedJobsHistoryLimit: 1      # 保留最近 1 次失败记录
  jobTemplate:
    spec:
      activeDeadlineSeconds: 50  # Job 超过 50s 自动终止
      template:
        spec:
          restartPolicy: OnFailure
          containers:
          - name: reporter
            image: busybox:1.28
            command:
            - /bin/sh
            - -c
            - |
              echo "=== 任务开始 ==="
              echo "执行时间: $(date '+%Y-%m-%d %H:%M:%S')"
              echo "节点主机名: $(hostname)"
              echo "Pod IP: $(hostname -i)"
              echo "=== 任务完成 ==="
            resources:
              requests:
                cpu: "10m"
                memory: "16Mi"
              limits:
                cpu: "100m"
                memory: "32Mi"
EOF
```

**验证（CronJob 已创建）**：

```bash
kubectl get cronjob report-job
```

预期输出：

```
NAME          SCHEDULE      SUSPEND   ACTIVE   LAST SCHEDULE   AGE
report-job    */1 * * * *   False     0        <none>          10s
```

---

### Step 2: 等待第一次触发并查看输出

**目标**：等待第一个 Job 被创建，查看执行日志。

```bash
# 持续监听 Job 创建（最多等 90 秒）
echo "等待 CronJob 触发（最多 90 秒）..."
kubectl wait --for=condition=Complete job \
  --selector=app.kubernetes.io/created-by="" \
  --timeout=90s 2>/dev/null || true

# 查看已创建的 Job 列表
kubectl get job -l app=report-job 2>/dev/null || kubectl get job | grep report
```

> CronJob 在下一个整分钟时刻触发（如创建于 xx:03:45，则 xx:04:00 第一次执行）。

**查看 Job 日志**：

```bash
# 找到最新一个 Pod
LATEST_POD=$(kubectl get pod --sort-by=.metadata.creationTimestamp | grep "report-job" | tail -1 | awk '{print $1}')
kubectl logs $LATEST_POD
```

预期输出：

```
=== 任务开始 ===
执行时间: 2026-xx-xx xx:xx:xx
节点主机名: report-job-xxxxxxxx-xxxxx
Pod IP: 10.42.x.x
=== 任务完成 ===
```

---

### Step 3: 手动触发一次 Job

**目标**：不等待定时触发，从 CronJob 手动创建一个立即执行的 Job。

```bash
# 从 CronJob 模板手动触发
kubectl create job manual-run-1 --from=cronjob/report-job

# 等待完成
kubectl wait --for=condition=Complete job/manual-run-1 --timeout=60s

# 查看日志
kubectl logs -l job-name=manual-run-1
```

预期输出：

```
=== 任务开始 ===
执行时间: 2026-xx-xx xx:xx:xx
节点主机名: manual-run-1-xxxxx
Pod IP: 10.42.x.x
=== 任务完成 ===
```

**关键点**：手动触发的 Job 与 CronJob 的调度完全独立，不影响原定时计划。

---

### Step 4: 查看历史 Job 记录

**目标**：观察 CronJob 自动清理旧 Job（只保留最近 3 次成功）。

等待 4-5 次触发后（约 5 分钟），执行：

```bash
# 查看所有 Job
kubectl get job

# 详细查看 CronJob 状态
kubectl describe cronjob report-job | grep -A20 "Events:"
```

预期输出（超过 3 个后最早的自动被删除）：

```
NAME                        COMPLETIONS   DURATION
report-job-xxxxxxxxxx       1/1           3s
report-job-yyyyyyyyyy       1/1           3s
report-job-zzzzzzzzzz       1/1           3s
manual-run-1                1/1           3s
```

> 自动触发的 Job 最多保留 3 个，更早的被自动清理。手动创建的 Job 不受此限制管理。

---

### Step 5: 测试超时机制

**目标**：创建一个会执行超时的 Job，验证 `activeDeadlineSeconds` 强制终止。

```bash
kubectl apply -f - <<'EOF'
apiVersion: batch/v1
kind: Job
metadata:
  name: timeout-test
spec:
  activeDeadlineSeconds: 10   # 10 秒后强制终止
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: sleeper
        image: busybox:1.28
        command: ["/bin/sh", "-c", "echo '开始执行'; sleep 60; echo '不会执行到这里'"]
        resources:
          requests:
            cpu: "10m"
            memory: "16Mi"
          limits:
            cpu: "100m"
            memory: "32Mi"
EOF

# 等待约 15 秒
sleep 15
kubectl get job timeout-test
kubectl describe job timeout-test | grep -A5 "Conditions:"
```

预期输出（Job 因超时被终止）：

```
Conditions:
  Type        Status    Reason
  Failed      True      DeadlineExceeded
```

---

### Step 6: 暂停和恢复 CronJob

**目标**：在维护窗口期间暂停定时触发，维护完成后恢复。

```bash
# 暂停 CronJob（不再触发新 Job）
kubectl patch cronjob report-job -p '{"spec":{"suspend":true}}'
kubectl get cronjob report-job

# 恢复 CronJob
kubectl patch cronjob report-job -p '{"spec":{"suspend":false}}'
kubectl get cronjob report-job
```

预期输出（SUSPEND 字段变化）：

```
# 暂停后：
NAME          SCHEDULE      SUSPEND   ACTIVE
report-job    */1 * * * *   True      0

# 恢复后：
NAME          SCHEDULE      SUSPEND   ACTIVE
report-job    */1 * * * *   False     0
```

---

## ✅ 验证整体完成

```bash
kubectl get cronjob report-job
kubectl get job | grep report
kubectl logs -l job-name=manual-run-1 --tail=5
```

预期（CronJob 正常运行，手动 Job 日志可查）：

```
NAME          SCHEDULE      SUSPEND   ACTIVE   LAST SCHEDULE
report-job    */1 * * * *   False     0        xx秒 ago
```

---

## 🧹 清理

```bash
kubectl delete cronjob report-job
kubectl delete job timeout-test manual-run-1 2>/dev/null; true

# 验证
kubectl get cronjob,job | grep -E "report|timeout|manual"
# 预期：无输出
```

---

## 🚀 扩展练习

1. **修改 Cron 表达式**：改为每 5 分钟（`*/5 * * * *`）或每小时整点（`0 * * * *`）
2. **并发策略对比**：把 `concurrencyPolicy` 改为 `Allow`，人为让 Job 执行时间超过 1 分钟，观察多个 Job 并发运行
3. **失败重试**：在脚本中加入 `exit 1`，观察 `backoffLimit` 控制重试次数的行为
4. **结合 PVC**：修改脚本把日志写入挂载的 PVC 文件，而非 stdout（与 D02 结合）
