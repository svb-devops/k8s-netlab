# 案例 D03: 蓝绿部署与滚动更新

## 📚 案例信息

- **难度**: ⭐⭐⭐（中级）
- **时长**: 35 分钟
- **环境**: K3s 单节点集群
- **前置**: 已有可用的 K8s 集群（建议先完成 D01）

## 🎯 你将完成什么

学习两种零停机部署策略：

**蓝绿部署**：同时运行新旧两个版本，切换 Service 选择器实现瞬间流量切换，出现问题可一键回滚。

**滚动更新**：Deployment 内置策略，逐步替换旧 Pod，全程不中断服务。

学完本案例，你将理解：
1. 蓝绿部署的切换原理——Service 标签选择器是流量的"开关"
2. 滚动更新的 `maxSurge` / `maxUnavailable` 参数含义
3. 如何用 `kubectl rollout` 查看历史、执行回滚

## 🏗️ 架构图

**蓝绿部署阶段**：

```
                ┌─────────────────────────────────┐
  app-svc ─────▶│  version: blue（nginx:1.24）     │  ← 生产流量
  （选择器）     └─────────────────────────────────┘
  
                ┌─────────────────────────────────┐
                │  version: green（nginx:1.25）    │  ← 待命（无流量）
                └─────────────────────────────────┘
```

**切换后**：

```
                ┌─────────────────────────────────┐
                │  version: blue（nginx:1.24）     │  ← 待命（保留备用）
                └─────────────────────────────────┘
  
  app-svc ─────▶┌─────────────────────────────────┐
  （选择器）     │  version: green（nginx:1.25）   │  ← 生产流量
                └─────────────────────────────────┘
```

## 🐳 使用的镜像

| 镜像 | 代表版本 | 来源 |
|------|---------|------|
| `nginx:1.24` | 蓝（当前生产版本） | 本地 registry mirror |
| `nginx:1.25` | 绿（新版本） | 本地 registry mirror |

## ⚠️ 开始前

确认集群就绪：

```bash
kubectl wait --for=condition=Ready node --all --timeout=120s
kubectl get node
```

---

## 🔬 步骤

---

### 第一部分：蓝绿部署

---

### Step 1: 部署蓝版本（当前生产）

**目标**：创建蓝版本 Deployment 和 Service，Service 初始指向蓝版本。

```bash
kubectl apply -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: app-blue
  labels:
    app: webserver
    version: blue
spec:
  replicas: 3
  selector:
    matchLabels:
      app: webserver
      version: blue
  template:
    metadata:
      labels:
        app: webserver
        version: blue
    spec:
      containers:
      - name: nginx
        image: nginx:1.24
        ports:
        - containerPort: 80
        resources:
          requests:
            cpu: "50m"
            memory: "64Mi"
          limits:
            cpu: "200m"
            memory: "128Mi"
---
apiVersion: v1
kind: Service
metadata:
  name: app-svc
spec:
  type: ClusterIP
  selector:
    app: webserver
    version: blue
  ports:
  - port: 80
    targetPort: 80
EOF
```

**验证**：

```bash
kubectl wait --for=condition=Available deployment/app-blue --timeout=60s
kubectl get pod -l version=blue
```

预期输出：

```
NAME                        READY   STATUS    RESTARTS   AGE
app-blue-xxxxxxxxx-aaaaa    1/1     Running   0          20s
app-blue-xxxxxxxxx-bbbbb    1/1     Running   0          20s
app-blue-xxxxxxxxx-ccccc    1/1     Running   0          20s
```

---

### Step 2: 部署绿版本（新版本待命）

**目标**：在同一集群部署新版本，但此时 Service 仍不指向绿版本——零流量影响。

```bash
kubectl apply -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: app-green
  labels:
    app: webserver
    version: green
spec:
  replicas: 3
  selector:
    matchLabels:
      app: webserver
      version: green
  template:
    metadata:
      labels:
        app: webserver
        version: green
    spec:
      containers:
      - name: nginx
        image: nginx:1.25
        ports:
        - containerPort: 80
        resources:
          requests:
            cpu: "50m"
            memory: "64Mi"
          limits:
            cpu: "200m"
            memory: "128Mi"
EOF
```

**验证**（绿版本就绪，流量仍走蓝版本）：

```bash
kubectl wait --for=condition=Available deployment/app-green --timeout=60s
kubectl get deployment app-blue app-green
```

预期输出：

```
NAME        READY   UP-TO-DATE   AVAILABLE
app-blue    3/3     3            3
app-green   3/3     3            3
```

---

### Step 3: 流量切换——蓝 → 绿

**目标**：修改 Service 选择器，将生产流量瞬间切换到绿版本。

```bash
# 切换前，确认当前 Service 指向蓝
kubectl get svc app-svc -o jsonpath='{.spec.selector}' && echo

# 执行切换（只改选择器，一行命令）
kubectl patch svc app-svc -p '{"spec":{"selector":{"app":"webserver","version":"green"}}}'
```

**验证**（切换后马上检查）：

```bash
# 确认 Service 选择器已更新
kubectl get svc app-svc -o jsonpath='{.spec.selector}' && echo

# 从内部发请求，确认响应来自 nginx:1.25 的 Pod
CLUSTER_IP=$(kubectl get svc app-svc -o jsonpath='{.spec.clusterIP}')
kubectl run test-curl --image=nginx --rm -it --restart=Never -- \
  sh -c "curl -s -o /dev/null -w '%{http_code}' http://$CLUSTER_IP"
```

预期输出：

```
{"app":"webserver","version":"green"}
200
```

**关键点**：切换动作只是修改了 Service 的 `.spec.selector`，不涉及任何 Pod 重建，整个切换在 1 秒内完成。

---

### Step 4: 验证回滚能力

**目标**：模拟新版本有问题，回滚到蓝版本——同样是一行命令。

```bash
# 模拟发现问题，切回蓝版本
kubectl patch svc app-svc -p '{"spec":{"selector":{"app":"webserver","version":"blue"}}}'

# 确认流量已回到蓝
kubectl get svc app-svc -o jsonpath='{.spec.selector}' && echo
```

预期输出：

```
{"app":"webserver","version":"blue"}
```

蓝版本一直在运行，回滚耗时与切换相同——不到 1 秒。

---

### 第二部分：滚动更新

---

### Step 5: 准备滚动更新实验

**目标**：删除蓝绿部署，用单个 Deployment 演示 K8s 内置的滚动更新。

```bash
# 清理蓝绿环境
kubectl delete deployment app-blue app-green
kubectl delete svc app-svc

# 创建新的单 Deployment 实验环境
kubectl apply -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rolling-app
spec:
  replicas: 4
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1        # 最多多出 1 个 Pod（升级过程中）
      maxUnavailable: 0  # 升级中不允许有 Pod 不可用
  selector:
    matchLabels:
      app: rolling-app
  template:
    metadata:
      labels:
        app: rolling-app
    spec:
      containers:
      - name: nginx
        image: nginx:1.24
        ports:
        - containerPort: 80
        resources:
          requests:
            cpu: "50m"
            memory: "64Mi"
          limits:
            cpu: "200m"
            memory: "128Mi"
EOF

kubectl wait --for=condition=Available deployment/rolling-app --timeout=60s
kubectl get pod -l app=rolling-app
```

预期输出（4 个 Pod Running）：

```
NAME                          READY   STATUS    RESTARTS   AGE
rolling-app-xxxxxxxxx-aaaa    1/1     Running   0          15s
rolling-app-xxxxxxxxx-bbbb    1/1     Running   0          15s
rolling-app-xxxxxxxxx-cccc    1/1     Running   0          15s
rolling-app-xxxxxxxxx-dddd    1/1     Running   0          15s
```

---

### Step 6: 执行滚动更新

**目标**：更新镜像版本，观察 Pod 逐步替换的过程。

打开两个终端并排执行：

**终端 1**（持续观察 Pod 状态）：
```bash
kubectl get pod -l app=rolling-app -w
```

**终端 2**（触发更新）：
```bash
kubectl set image deployment/rolling-app nginx=nginx:1.25
```

预期在终端 1 看到的过程（`maxSurge=1` 意味着同时最多 5 个 Pod）：

```
rolling-app-old-aaaa    1/1     Running       → Terminating
rolling-app-old-bbbb    1/1     Running
rolling-app-new-eeee    0/1     Pending       → Running
rolling-app-old-bbbb    1/1     Running       → Terminating
rolling-app-new-ffff    0/1     Pending       → Running
...（直至全部替换完成）
```

**关键点**：`maxUnavailable=0` 保证全程至少有 4 个 Pod 在提供服务，用户感知不到中断。

---

### Step 7: 查看更新历史

**目标**：查看 Deployment 的 rollout 历史记录。

```bash
kubectl rollout history deployment/rolling-app
```

预期输出：

```
REVISION  CHANGE-CAUSE
1         <none>
2         <none>
```

> Revision 1 = nginx:1.24，Revision 2 = nginx:1.25

查看具体版本详情：

```bash
kubectl rollout history deployment/rolling-app --revision=1
kubectl rollout history deployment/rolling-app --revision=2
```

---

### Step 8: 执行回滚

**目标**：回滚到上一个版本（nginx:1.24），验证 K8s 保存了历史状态。

```bash
# 回滚到上一个版本
kubectl rollout undo deployment/rolling-app

# 观察回滚过程
kubectl rollout status deployment/rolling-app
```

预期输出：

```
Waiting for deployment "rolling-app" rollout to finish: 1 out of 4 new replicas have been updated...
...
deployment "rolling-app" successfully rolled out
```

**验证回滚结果**：

```bash
kubectl get deployment rolling-app -o jsonpath='{.spec.template.spec.containers[0].image}' && echo
```

预期输出：

```
nginx:1.24
```

---

## ✅ 验证整体完成

```bash
# 查看最终 Deployment 状态
kubectl get deployment rolling-app
kubectl rollout history deployment/rolling-app
```

预期输出（3 个 revision，最后一次是 undo 产生的新 revision）：

```
NAME          READY   UP-TO-DATE   AVAILABLE
rolling-app   4/4     4            4

REVISION  CHANGE-CAUSE
1         <none>
2         <none>
3         <none>
```

---

## 🧹 清理

```bash
kubectl delete deployment rolling-app
```

如果之前没有删除蓝绿资源，一并清理：

```bash
kubectl delete deployment app-blue app-green 2>/dev/null; true
kubectl delete svc app-svc 2>/dev/null; true
```

---

## 🚀 扩展练习

1. **调整参数**：把 `maxSurge=2, maxUnavailable=1`，重新执行更新，观察替换速度变化
2. **暂停/继续**：更新途中执行 `kubectl rollout pause deployment/rolling-app`，再 `resume`
3. **回滚到指定版本**：`kubectl rollout undo deployment/rolling-app --to-revision=1`
4. **记录变更原因**：加 `--record` 标志（或用 `kubernetes.io/change-cause` annotation），让 `rollout history` 显示有意义的 CHANGE-CAUSE
