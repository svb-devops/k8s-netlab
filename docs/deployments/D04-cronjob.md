# 案例 D04: CronJob 定时任务系统

## 📚 案例信息

- **难度**: ⭐⭐⭐（中级）
- **时长**: 30 分钟
- **环境**: K3s 单节点集群
- **前置**: 了解 Pod 基础概念

## 🎯 你将完成什么

用 K8s CronJob 创建定时任务，周期性自动运行 Job：

- 创建每分钟执行一次的 CronJob
- 观察 CronJob → Job → Pod 的三层创建过程
- 查看 Pod 日志验证任务执行结果
- 删除 CronJob 并确认关联 Job 和 Pod 被一并清理

学完本案例，你将理解：
1. CronJob、Job、Pod 三者的层级关系和生命周期
2. Cron 表达式在 K8s 中的格式（与 Linux crontab 一致）
3. `restartPolicy: OnFailure` 的含义——任务失败时重试，而非重启 Pod

## 🏗️ 架构图

```
CronJob（schedule: "* * * * *"）
    │ 每分钟触发
    ▼
 Job（自动创建，名称带时间戳）
    │
    ▼
 Pod（执行 date + echo，完成后 Completed）
```

## 🐳 使用的镜像

| 镜像 | 用途 | 来源 |
|------|------|------|
| `busybox:1.28` | 执行 shell 命令（date、echo） | 本地 registry mirror |

## ⚠️ 开始前

确认集群就绪：

```bash
kubectl wait --for=condition=Ready node --all --timeout=120s
kubectl get node
```

---

## 🔬 步骤

### Step 1: 创建 CronJob

**目标**：创建每分钟执行一次的 CronJob，打印时间和欢迎信息。

```bash
kubectl apply -f - <<'EOF'
apiVersion: batch/v1
kind: CronJob
metadata:
  name: hello
spec:
  schedule: "* * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: hello
            image: busybox:1.28
            imagePullPolicy: IfNotPresent
            command:
            - /bin/sh
            - -c
            - date; echo Hello from the Kubernetes cluster
          restartPolicy: OnFailure
EOF
```

**验证**（CronJob 已创建）：

```bash
kubectl get cronjob hello
```

预期输出：

```
NAME    SCHEDULE    SUSPEND   ACTIVE   LAST SCHEDULE   AGE
hello   * * * * *   False     0        <none>          10s
```

---

### Step 2: 监听 Job 执行

**目标**：等待第一个 Job 被触发，观察 Job 从 0/1 到 1/1 的完成过程。

```bash
kubectl get jobs --watch
```

预期输出（约 1 分钟后出现）：

```
NAME               COMPLETIONS   DURATION   AGE
hello-4111706356   0/1                      0s
hello-4111706356   0/1           0s         0s
hello-4111706356   1/1           5s         5s
```

按 Ctrl+C 停止监听。

---

### Step 3: 查看执行结果

**目标**：通过 Pod 日志确认 CronJob 执行了正确的命令。

```bash
# 确认 CronJob 已调度（LAST SCHEDULE 已更新）
kubectl get cronjob hello

# 找到 Job 创建的 Pod
pods=$(kubectl get pods --selector=job-name=hello-4111706356 \
  --output=jsonpath={.items[*].metadata.name})

# 查看 Pod 日志
kubectl logs $pods
```

> 注意：将 `hello-4111706356` 替换为实际的 Job 名称（`kubectl get jobs` 可查看）。

预期输出：

```
Fri Feb 22 11:02:09 UTC 2019
Hello from the Kubernetes cluster
```

---

### Step 4: 观察多次执行历史

等待 3-4 分钟后，查看 CronJob 的调度历史：

```bash
kubectl get cronjob hello
kubectl get jobs
kubectl get pods --selector=job-name
```

预期（CronJob 每分钟创建一个 Job，K8s 默认保留最近 3 次成功和 1 次失败）：

```
NAME    SCHEDULE    LAST SCHEDULE   AGE
hello   * * * * *   23s             4m

NAME               COMPLETIONS   AGE
hello-4111706356   1/1           3m
hello-4111706357   1/1           2m
hello-4111706358   1/1           1m
```

---

## ✅ 验证整体完成

```bash
kubectl get cronjob hello
```

LAST SCHEDULE 显示最近一次调度时间，即为完成标志。

---

## 🧹 清理

```bash
kubectl delete cronjob hello
```

**重要**：删除 CronJob 会同时删除所有关联的 Job 和 Pod，并停止后续调度。

验证清理完成：

```bash
kubectl get jobs
kubectl get pods
# 预期：hello 相关资源全部消失
```

---

## 🚀 扩展练习

1. **修改 Cron 表达式**：改为每 5 分钟（`*/5 * * * *`）或每小时整点（`0 * * * *`）
2. **任务失败重试**：把命令改为 `exit 1`（必然失败），观察 Pod 如何按 `restartPolicy: OnFailure` 重试
3. **并发控制**：加 `concurrencyPolicy: Forbid` 字段，防止上一个 Job 未完成时触发新的
4. **手动触发**：`kubectl create job manual-test --from=cronjob/hello`，立即触发一次而不等定时
