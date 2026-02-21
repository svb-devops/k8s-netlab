# 实验10: 监控和日志管理

## 📋 实验信息

- **难度**: ⭐⭐⭐ (中级)
- **时长**: 35-40分钟
- **环境**: K3s单节点集群
- **前置**: 完成实验1-3，理解Pod基础

## 🎯 学习目标

通过本实验，你将：
1. 理解Kubernetes日志管理机制
2. 掌握kubectl logs命令的各种用法
3. 学习多容器Pod的日志查看
4. 掌握查看崩溃容器的历史日志
5. 学习metrics-server资源监控
6. 掌握kubectl top命令查看资源使用
7. 理解Events事件系统和故障排查流程

## 📚 前置知识

- 完成实验1-3，理解Pod基础
- 了解容器标准输出概念
- 理解Pod和容器的关系
- 了解资源请求和限制

---

## 🐳 实验镜像说明

本实验使用的镜像：

### nginx
- **用途**: 生成访问日志
- **场景**: 模拟Web应用日志

### busybox:1.28
- **用途**: 生成自定义日志、模拟崩溃
- **场景**: 测试各种日志查看场景

**💡 监控日志实验特点:**
- 演示kubectl logs各种参数
- 模拟真实故障排查流程
- 理解Kubernetes日志存储机制
- 学习资源监控方法

**📖 关于Kubernetes日志:**
- 容器日志 = 进程标准输出（stdout/stderr）
- kubelet将日志保存到节点文件系统
- 日志有大小和文件数限制（默认10MB×5个）
- Pod删除后日志随之消失

---

## ⚠️ 开始实验前

VM刚启动时，K3s需要约2-3分钟完成初始化。请先确认环境就绪：

```bash
# 等待节点Ready
kubectl wait --for=condition=Ready node --all --timeout=180s

# 确认系统Pod运行正常
kubectl get pod -n kube-system
```

如果看到节点NotReady或大量Pod处于Pending，请等待2-3分钟再继续。

---

## 🚀 实验步骤

### Step 1: Pod日志基本查看

**开始前快速检查:**

```bash
# 确认环境就绪
kubectl get node
```

**创建一个持续产生日志的Pod:**

```bash
cat > log-generator.yaml <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: log-generator
spec:
  containers:
  - name: app
    image: busybox:1.28
    command: ["sh", "-c"]
    args:
    - |
      i=0
      while true; do
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO: Request #\$i processed"
        i=\$((i+1))
        sleep 2
      done
EOF

kubectl apply -f log-generator.yaml

# 等待Pod运行
kubectl wait --for=condition=Ready pod/log-generator --timeout=60s
```

**基本日志查看命令:**

```bash
# 查看全部日志
kubectl logs log-generator

# 持续追踪日志（类似 tail -f）
kubectl logs log-generator -f
```

按 `Ctrl+C` 退出追踪。

```bash
# 只查看最后10行
kubectl logs log-generator --tail=10

# 查看最近1分钟的日志
kubectl logs log-generator --since=1m

# 查看最近30秒的日志
kubectl logs log-generator --since=30s

# 带时间戳显示
kubectl logs log-generator --timestamps=true --tail=5
```

**预期输出示例:**
```
[2026-02-19 08:30:01] INFO: Request #0 processed
[2026-02-19 08:30:03] INFO: Request #1 processed
[2026-02-19 08:30:05] INFO: Request #2 processed
```

**验证点:** ✅ 掌握kubectl logs基本参数（-f、--tail、--since、--timestamps）

**💡 知识点:**
- `kubectl logs <pod>` 查看当前日志
- `-f` 持续追踪，实时输出
- `--tail=N` 只看最后N行
- `--since=Xs/m/h` 按时间过滤
- `--timestamps` 显示精确时间戳
- Kubernetes日志 = 容器stdout/stderr

---

### Step 2: 多容器Pod的日志查看

**创建多容器Pod:**

```bash
cat > multi-container.yaml <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: multi-container
spec:
  containers:
  - name: app
    image: busybox:1.28
    command: ["sh", "-c"]
    args:
    - |
      while true; do
        echo "[APP] Processing request at \$(date)"
        sleep 3
      done
  - name: sidecar
    image: busybox:1.28
    command: ["sh", "-c"]
    args:
    - |
      while true; do
        echo "[SIDECAR] Health check OK at \$(date)"
        sleep 5
      done
EOF

kubectl apply -f multi-container.yaml
kubectl wait --for=condition=Ready pod/multi-container --timeout=60s
```

**分别查看各容器日志:**

```bash
# 不指定容器时默认使用第一个容器（会有提示信息）
kubectl logs multi-container

# 指定 app 容器
kubectl logs multi-container -c app --tail=5

# 指定 sidecar 容器
kubectl logs multi-container -c sidecar --tail=5
```

**查看所有容器日志（加前缀区分）:**

```bash
# --all-containers 查看所有容器，--prefix 加容器名前缀
kubectl logs multi-container --all-containers=true --prefix=true --tail=5
```

**预期输出:**
```
[pod/multi-container/app] [APP] Processing request at Thu Feb 19 08:30:01 UTC 2026
[pod/multi-container/sidecar] [SIDECAR] Health check OK at Thu Feb 19 08:30:00 UTC 2026
```

**验证点:** ✅ 掌握多容器Pod日志查看，使用 -c 指定容器

**💡 知识点:**
- 多容器Pod不指定容器时默认第一个（会显示 "Defaulted container ..." 提示）
- 建议用 `-c <container>` 明确指定容器，避免歧义
- `--all-containers` 一次查看所有容器
- `--prefix` 显示容器名前缀，便于区分
- 每个容器日志独立存储

---

### Step 3: 查看崩溃容器的历史日志

**创建一个会崩溃重启的Pod:**

```bash
cat > crash-pod.yaml <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: crash-demo
spec:
  containers:
  - name: app
    image: busybox:1.28
    command: ["sh", "-c"]
    args:
    - |
      echo "Starting application..."
      echo "Connecting to database..."
      sleep 5
      echo "ERROR: Database connection failed!"
      echo "Application crashed!" >&2
      exit 1
  restartPolicy: Always
EOF

kubectl apply -f crash-pod.yaml

# 观察Pod重启
kubectl get pod crash-demo -w
```

等待Pod显示 `CrashLoopBackOff` 或 `Error` 状态后，按 `Ctrl+C`。

```bash
# 查看当前容器日志（可能是空的，因为刚重启）
kubectl logs crash-demo

# 查看上一次（崩溃的）容器日志
kubectl logs crash-demo --previous

# 查看Pod重启次数和状态
kubectl get pod crash-demo
kubectl describe pod crash-demo | grep -A 10 "Last State:"
```

**预期 --previous 输出:**
```
Starting application...
Connecting to database...
ERROR: Database connection failed!
Application crashed!
```

**验证点:** ✅ 使用 --previous 查看已崩溃容器的日志

**💡 知识点:**
- `--previous` 查看上次运行的容器日志
- 容器崩溃重启后，当前日志从头开始
- 崩溃信息往往在 `--previous` 中
- 结合 `kubectl describe` 查看 Last State
- `CrashLoopBackOff` 是最常见的崩溃状态

---

### Step 4: 资源使用监控

**检查metrics-server是否可用:**

```bash
# K3s默认集成metrics-server
kubectl top nodes
```

**如果命令报错（metrics-server未就绪），等待30秒再试:**

```bash
# 检查metrics-server状态
kubectl get pod -n kube-system | grep metrics

# 等待metrics-server就绪
kubectl wait --for=condition=Ready pod -l k8s-app=metrics-server -n kube-system --timeout=60s
```

**查看节点资源使用:**

```bash
# 查看节点CPU和内存
kubectl top nodes
```

**预期输出:**
```
NAME     CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
k3s-vm   125m         6%     512Mi           25%
```

**创建负载Pod并监控资源:**

```bash
cat > resource-demo.yaml <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: resource-demo
  labels:
    app: resource-demo
spec:
  containers:
  - name: app
    image: nginx
    resources:
      requests:
        memory: "64Mi"
        cpu: "50m"
      limits:
        memory: "128Mi"
        cpu: "100m"
EOF

kubectl apply -f resource-demo.yaml
kubectl wait --for=condition=Ready pod/resource-demo --timeout=60s

# 查看Pod资源使用
kubectl top pod resource-demo

# 查看所有Pod资源使用
kubectl top pods

# 按CPU排序
kubectl top pods --sort-by=cpu

# 按内存排序
kubectl top pods --sort-by=memory
```

**预期输出:**
```
NAME            CPU(cores)   MEMORY(bytes)
resource-demo   1m           4Mi
```

**查看资源请求和限制:**

```bash
kubectl describe pod resource-demo | grep -A 8 "Limits:"
```

**验证点:** ✅ 使用kubectl top查看节点和Pod的资源使用

**💡 知识点:**
- `kubectl top nodes` 查看节点资源
- `kubectl top pods` 查看Pod资源
- `--sort-by=cpu/memory` 排序
- metrics-server提供实时资源数据
- requests：调度保障；limits：上限限制
- CPU单位：m（毫核），1000m = 1核
- 内存单位：Mi（兆字节），Gi（吉字节）

---

### Step 5: 事件查看和分析

**Kubernetes事件记录集群中发生的一切:**

```bash
# 查看所有事件
kubectl get events

# 按时间排序
kubectl get events --sort-by='.lastTimestamp'

# 只看Warning级别的事件
kubectl get events --field-selector type=Warning

# 查看特定Pod的事件
kubectl describe pod crash-demo | grep -A 20 "Events:"
```

**预期events输出:**
```
LAST SEEN   TYPE      REASON              OBJECT              MESSAGE
5m          Normal    Scheduled           Pod/crash-demo      Successfully assigned default/crash-demo
5m          Normal    Pulling             Pod/crash-demo      Pulling image "busybox:1.28"
5m          Normal    Pulled              Pod/crash-demo      Successfully pulled image
5m          Normal    Created             Pod/crash-demo      Created container app
5m          Normal    Started             Pod/crash-demo      Started container app
4m          Warning   BackOff             Pod/crash-demo      Back-off restarting failed container
```

**创建一个无法调度的Pod（观察Warning事件）:**

```bash
cat > unschedulable.yaml <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: unschedulable-demo
spec:
  containers:
  - name: app
    image: nginx
    resources:
      requests:
        memory: "100Gi"   # 申请超大内存，无法调度
        cpu: "100"
EOF

kubectl apply -f unschedulable.yaml

# 等几秒后查看事件
sleep 5
kubectl get events --field-selector reason=FailedScheduling

# 查看Pod状态
kubectl get pod unschedulable-demo
kubectl describe pod unschedulable-demo | tail -10
```

**预期输出:**
```
Warning  FailedScheduling  pod/unschedulable-demo  0/1 nodes are available: 1 Insufficient memory, 1 Insufficient cpu.
```

**清理无法调度的Pod:**

```bash
kubectl delete pod unschedulable-demo
rm -f unschedulable.yaml
```

**验证点:** ✅ 掌握kubectl get events和describe查看事件

**💡 知识点:**
- Events记录集群中所有重要操作
- Normal：正常操作；Warning：需要关注
- `--sort-by='.lastTimestamp'` 按时间排序
- `--field-selector type=Warning` 过滤警告
- `kubectl describe` 包含最近Events
- Events默认保留1小时

---

### Step 6: 综合故障排查演练

**模拟一个真实的故障场景并完整排查:**

```bash
# 创建一个有配置错误的Pod（错误的镜像名）
cat > broken-app.yaml <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: broken-app
  labels:
    app: broken-app
spec:
  containers:
  - name: web
    image: nginx:nonexistent-tag   # 错误的镜像标签
    ports:
    - containerPort: 80
EOF

kubectl apply -f broken-app.yaml
```

**按照标准排查流程逐步诊断:**

```bash
# 1. 检查Pod状态
echo "=== Step 1: 查看Pod状态 ==="
kubectl get pod broken-app

# 2. 查看详细描述（最重要）
echo "=== Step 2: 查看Pod详情 ==="
kubectl describe pod broken-app

# 3. 查看日志（可能为空，因为容器未启动）
echo "=== Step 3: 查看日志 ==="
kubectl logs broken-app 2>&1 || echo "容器未启动，无日志"

# 4. 查看Events
echo "=== Step 4: 查看Events ==="
kubectl get events --field-selector involvedObject.name=broken-app
```

**预期排查结果:**
```
=== Step 1: 查看Pod状态 ===
NAME         READY   STATUS             RESTARTS
broken-app   0/1     ErrImagePull       0

=== Step 4: 查看Events ===
Warning  Failed   pod/broken-app   Failed to pull image "nginx:nonexistent-tag": ...
```

**标准故障排查流程总结:**

```bash
# 完整排查脚本（可复用）
echo "========== Pod故障排查 =========="
POD=broken-app

echo "1. Pod基本状态:"
kubectl get pod $POD

echo ""
echo "2. Pod详细描述:"
kubectl describe pod $POD | tail -20

echo ""
echo "3. 容器日志:"
kubectl logs $POD --tail=20 2>&1 || echo "(容器未启动)"

echo ""
echo "4. 历史日志（如有重启）:"
kubectl logs $POD --previous --tail=20 2>&1 || echo "(无历史日志)"

echo ""
echo "5. 相关Events:"
kubectl get events --field-selector involvedObject.name=$POD --sort-by='.lastTimestamp'
```

**清理故障演练资源:**

```bash
kubectl delete pod broken-app
rm -f broken-app.yaml
```

**验证点:** ✅ 掌握完整的Pod故障排查流程

**💡 知识点:**
- 排查顺序：状态 → 描述 → 日志 → 事件
- `ErrImagePull`：镜像拉取失败
- `ImagePullBackOff`：持续失败后进入退避
- `CrashLoopBackOff`：容器持续崩溃
- `OOMKilled`：内存超限被Kill
- `Pending`：调度失败，看Events

---

## ✅ 验证清单

- [ ] 掌握kubectl logs基本用法（-f、--tail、--since）
- [ ] 理解多容器Pod日志查看（-c参数）
- [ ] 学会查看崩溃容器历史日志（--previous）
- [ ] 使用kubectl top查看资源使用
- [ ] 掌握kubectl get events查看事件
- [ ] 完成综合故障排查演练
- [ ] 理解标准的Pod故障排查流程

---

## 🔧 故障排查

### 问题1: kubectl top 报错

**原因:** metrics-server未就绪

**解决:**
```bash
# 检查metrics-server状态
kubectl get pod -n kube-system | grep metrics

# 等待就绪（K3s启动后需要约1-2分钟）
kubectl wait --for=condition=Ready pod -l k8s-app=metrics-server \
  -n kube-system --timeout=120s

# 再试
kubectl top nodes
```

---

### 问题2: kubectl logs 显示空

**原因1:** 容器刚启动，还没有日志

**原因2:** 容器已崩溃，需要用 --previous

```bash
# 确认容器状态
kubectl get pod <pod-name>

# 如有重启，查看历史日志
kubectl logs <pod-name> --previous
```

---

### 问题3: 日志被截断（看不到早期日志）

**原因:** 日志超过kubelet保留限制（默认10MB）

**解决:**
```bash
# 查看特定时间段的日志
kubectl logs <pod-name> --since=1h --tail=1000

# 或指定时间点
kubectl logs <pod-name> --since-time="2026-02-19T08:00:00Z"
```

---

### 问题4: Events已过期看不到

**原因:** Events默认只保留1小时

**解决:**
```bash
# 查看Pod描述，通常包含最近Events
kubectl describe pod <pod-name>

# 检查节点级别的事件
kubectl get events -n kube-system --sort-by='.lastTimestamp'
```

---

## 🧪 扩展练习

### 1. 日志标签筛选

查看同一标签下所有Pod的日志：

```bash
# 查看所有带 app=nginx 标签的Pod日志
kubectl logs -l app=nginx --tail=10

# 组合 --all-containers
kubectl logs -l app=nginx --all-containers=true --prefix=true --tail=5
```

### 2. 资源使用统计

```bash
# 查看命名空间下所有Pod资源
kubectl top pods -n kube-system --sort-by=memory

# 查看所有命名空间
kubectl top pods --all-namespaces
```

### 3. 自定义日志格式输出

```bash
# 以JSON格式查看Events
kubectl get events -o json | python3 -m json.tool | head -50

# 自定义列显示
kubectl get events \
  -o custom-columns='TIME:.lastTimestamp,TYPE:.type,REASON:.reason,MESSAGE:.message' \
  --sort-by='.lastTimestamp'
```

---

## 📖 知识总结

### kubectl logs 命令速查

| 参数 | 说明 | 示例 |
|------|------|------|
| 无参数 | 查看当前日志 | `kubectl logs pod-name` |
| `-f` | 持续追踪 | `kubectl logs pod-name -f` |
| `--tail=N` | 最后N行 | `kubectl logs pod-name --tail=50` |
| `--since=Xm` | 最近X分钟 | `kubectl logs pod-name --since=5m` |
| `--timestamps` | 显示时间戳 | `kubectl logs pod-name --timestamps` |
| `-c <name>` | 指定容器 | `kubectl logs pod-name -c app` |
| `--previous` | 上次容器日志 | `kubectl logs pod-name --previous` |
| `--all-containers` | 所有容器 | `kubectl logs pod-name --all-containers` |
| `-l <label>` | 按标签筛选 | `kubectl logs -l app=nginx` |

### Pod常见状态和排查方向

| 状态 | 含义 | 排查方向 |
|------|------|---------|
| `Pending` | 未调度 | Events（资源不足、节点选择器） |
| `ErrImagePull` | 镜像拉取失败 | 镜像名/标签/仓库权限 |
| `ImagePullBackOff` | 镜像拉取持续失败 | 同上，等待退避中 |
| `CrashLoopBackOff` | 容器持续崩溃 | `logs --previous`，查看退出原因 |
| `OOMKilled` | 内存超限 | 增加memory limit |
| `Running` 但不Ready | 就绪探针失败 | describe查看探针配置 |
| `Terminating` 卡住 | 优雅退出超时 | 检查terminationGracePeriod |

### 故障排查标准流程

```
1. kubectl get pod           → 看状态
2. kubectl describe pod      → 看Events和配置
3. kubectl logs              → 看应用日志
4. kubectl logs --previous   → 看崩溃前日志
5. kubectl top pod           → 看资源使用
6. kubectl get events        → 看集群事件
```

### 资源监控说明

**metrics-server:**
- K3s默认集成
- 提供实时CPU/内存数据
- kubectl top 依赖此组件
- 数据每15秒刷新一次

**资源单位:**
- CPU：`m`（毫核），100m = 0.1核
- 内存：`Mi`（MiB），`Gi`（GiB）

**requests vs limits:**
- requests：调度保障（最低保证）
- limits：使用上限（超出会被限制/Kill）

---

## 🧹 清理环境

```bash
# 删除本实验创建的所有资源
kubectl delete pod log-generator multi-container crash-demo resource-demo 2>/dev/null

# 删除配置文件
rm -f log-generator.yaml multi-container.yaml crash-pod.yaml resource-demo.yaml

# 验证清理完成
kubectl get pod
```

---

## 📎 参考资料

- [kubectl logs文档](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_logs/)
- [应用调试指南](https://kubernetes.io/docs/tasks/debug/debug-application/)
- [metrics-server项目](https://github.com/kubernetes-sigs/metrics-server)

---

**实验10完成！** 🎉

继续下一个实验前，确保理解：
- kubectl logs各种参数的使用场景
- 多容器Pod日志查看方法
- 崩溃容器历史日志的查看
- kubectl top资源监控
- Events事件系统的作用
- 完整的Pod故障排查流程
