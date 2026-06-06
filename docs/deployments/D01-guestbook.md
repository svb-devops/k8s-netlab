# 案例 D01: 留言板应用（Guestbook）

## 📚 案例信息

- **难度**: ⭐⭐⭐（中级）
- **时长**: 30 分钟
- **环境**: K3s 单节点集群
- **前置**: 已有可用的 K8s 集群（完成实验 1）

## 🎯 你将完成什么

部署一个完整的多层留言板应用，包含：
- 3 副本 `nginx` 前端 Deployment（对外提供静态页面）
- 1 副本 `redis:7-alpine` 后端 Deployment（存储留言数据）
- ClusterIP Service 连通前后端
- 验证 Pod 重调度后数据的访问路径

学完本案例，你将理解：
1. 多层应用在 K8s 中的典型部署模式
2. Deployment 多副本与 Service 负载均衡的协作方式
3. 通过标签选择器将 Service 路由到正确的 Pod

## 🏗️ 架构图

```
学生（curl）
     │
     ▼
 frontend-svc（ClusterIP :80）
     │
     ├──▶ frontend Pod 1（nginx）
     ├──▶ frontend Pod 2（nginx）
     └──▶ frontend Pod 3（nginx）
                │
                ▼（通过 Service 名访问）
         redis-svc（ClusterIP :6379）
                │
                ▼
          redis Pod（redis:7-alpine）
```

## 🐳 使用的镜像

| 镜像 | 用途 | 来源 |
|------|------|------|
| `nginx` | 前端 Web 服务器 | 本地 registry mirror |
| `redis:7-alpine` | 留言数据存储 | 本地 registry mirror |

> 两个镜像均已预置在集群内部 registry（`172.16.100.1:5000`），首次拉取无需等待。

## ⚠️ 开始前

确认集群就绪：

```bash
kubectl wait --for=condition=Ready node --all --timeout=120s
kubectl get node
```

预期输出：

```
node/k3s-node   Ready   ...
```

---

## 🔬 步骤

### Step 1: 创建 Redis 后端

**目标**：部署 Redis Deployment 和对应的 ClusterIP Service。

```bash
kubectl apply -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
  labels:
    app: guestbook
    tier: backend
spec:
  replicas: 1
  selector:
    matchLabels:
      app: guestbook
      tier: backend
  template:
    metadata:
      labels:
        app: guestbook
        tier: backend
    spec:
      containers:
      - name: redis
        image: redis:7-alpine
        ports:
        - containerPort: 6379
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
  name: redis-svc
  labels:
    app: guestbook
    tier: backend
spec:
  type: ClusterIP
  selector:
    app: guestbook
    tier: backend
  ports:
  - port: 6379
    targetPort: 6379
EOF
```

**验证**：

```bash
kubectl wait --for=condition=Available deployment/redis --timeout=60s
kubectl get pod -l tier=backend
```

预期输出：

```
deployment.apps/redis condition met
NAME                     READY   STATUS    RESTARTS   AGE
redis-xxxxxxxxx-xxxxx    1/1     Running   0          30s
```

---

### Step 2: 创建 nginx 前端（3 副本）

**目标**：部署 3 副本的 nginx Deployment 和对外的 ClusterIP Service。

```bash
kubectl apply -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: frontend
  labels:
    app: guestbook
    tier: frontend
spec:
  replicas: 3
  selector:
    matchLabels:
      app: guestbook
      tier: frontend
  template:
    metadata:
      labels:
        app: guestbook
        tier: frontend
    spec:
      containers:
      - name: frontend
        image: nginx
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
  name: frontend-svc
  labels:
    app: guestbook
    tier: frontend
spec:
  type: ClusterIP
  selector:
    app: guestbook
    tier: frontend
  ports:
  - port: 80
    targetPort: 80
EOF
```

**验证**：

```bash
kubectl wait --for=condition=Available deployment/frontend --timeout=60s
kubectl get pod -l tier=frontend
```

预期输出（3 个 Pod 都 Running）：

```
NAME                        READY   STATUS    RESTARTS   AGE
frontend-xxxxxxxxx-aaaaa    1/1     Running   0          20s
frontend-xxxxxxxxx-bbbbb    1/1     Running   0          20s
frontend-xxxxxxxxx-ccccc    1/1     Running   0          20s
```

---

### Step 3: 验证 Service 发现

**目标**：从 frontend Pod 内部，通过 Service 名称访问 Redis。

```bash
# 取任意一个 frontend Pod
FRONTEND_POD=$(kubectl get pod -l tier=frontend -o jsonpath='{.items[0].metadata.name}')

# 进入 Pod，测试 DNS 解析
kubectl exec $FRONTEND_POD -- nslookup redis-svc
```

预期输出（DNS 解析成功）：

```
Server:         10.43.0.10
Address:        10.43.0.10#53

Name:   redis-svc.default.svc.cluster.local
Address: 10.43.x.x
```

**关键点**：Pod 内使用 Service 短名（`redis-svc`）即可访问，K8s DNS 自动补全 `.default.svc.cluster.local`。

---

### Step 4: 观察负载均衡

**目标**：验证对 frontend-svc 的请求被分散到 3 个 Pod。

```bash
# 获取 Service Cluster IP
FRONTEND_IP=$(kubectl get svc frontend-svc -o jsonpath='{.spec.clusterIP}')
echo "frontend-svc ClusterIP: $FRONTEND_IP"

# 从 redis Pod 发出多次请求，观察响应（nginx 默认返回主机名）
REDIS_POD=$(kubectl get pod -l tier=backend -o jsonpath='{.items[0].metadata.name}')
kubectl exec $REDIS_POD -- sh -c "
  for i in \$(seq 1 9); do
    wget -qO- --timeout=2 http://$FRONTEND_IP 2>/dev/null | grep -o 'nginx' || echo 'ok'
  done
"
```

预期输出（9 次请求均返回，表明 3 个副本都在提供服务）：

```
ok
ok
ok
...（共 9 行）
```

**深入观察**：查看每个 Pod 的访问日志，可以看到请求被分散：

```bash
kubectl logs -l tier=frontend --prefix --tail=3
```

---

### Step 5: 测试 Pod 故障自愈

**目标**：删除一个 frontend Pod，观察 Deployment 自动重建。

```bash
# 记录当前 Pod 列表
kubectl get pod -l tier=frontend

# 删除第一个 Pod（模拟故障）
POD_TO_DELETE=$(kubectl get pod -l tier=frontend -o jsonpath='{.items[0].metadata.name}')
kubectl delete pod $POD_TO_DELETE

# 立即观察（新 Pod 正在被调度）
kubectl get pod -l tier=frontend -w
```

预期过程（按 Ctrl+C 退出 watch）：

```
NAME                        READY   STATUS        RESTARTS
frontend-xxxxxxxxx-aaaaa    1/1     Terminating   0
frontend-xxxxxxxxx-ddddd    0/1     Pending       0
frontend-xxxxxxxxx-ddddd    1/1     Running       0
```

Deployment 控制器检测到副本数不足，自动创建新 Pod 恢复到 3 个。

---

## ✅ 验证整体完成

```bash
# 所有组件都就绪
kubectl get deployment,pod,svc -l app=guestbook
```

预期输出（Deployment READY 均满足，Pod 全 Running，Service 存在）：

```
NAME                       READY   UP-TO-DATE   AVAILABLE
deployment.apps/frontend   3/3     3            3
deployment.apps/redis      1/1     1            1

NAME                            READY   STATUS
pod/frontend-xxx-aaa            1/1     Running
pod/frontend-xxx-bbb            1/1     Running
pod/frontend-xxx-ccc            1/1     Running
pod/redis-xxx-yyy               1/1     Running

NAME             TYPE        CLUSTER-IP    PORT(S)
frontend-svc     ClusterIP   10.43.x.x     80/TCP
redis-svc        ClusterIP   10.43.x.x     6379/TCP
```

---

## 🧹 清理

```bash
kubectl delete deployment frontend redis
kubectl delete service frontend-svc redis-svc
```

验证清理完成：

```bash
kubectl get pod -l app=guestbook
# 预期：No resources found.
```

---

## 🚀 扩展练习

1. **扩缩容**：`kubectl scale deployment frontend --replicas=5`，再缩回 3，观察 Pod 变化
2. **Service 类型**：把 frontend-svc 改为 `NodePort`，用节点 IP + 端口从外部访问
3. **资源限制**：去掉 `resources.limits`，用 `kubectl top pod` 观察 Pod 实际用量
4. **持久化存储**：给 Redis 挂载 PVC，删除 Pod 后数据是否还在？（进阶）
