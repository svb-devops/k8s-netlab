# 案例 D01: 留言板应用（Guestbook）

## 📚 案例信息

- **难度**: ⭐⭐⭐（中级）
- **时长**: 30 分钟
- **环境**: K3s 单节点集群
- **前置**: 已有可用的 K8s 集群（完成实验 1）

## 🎯 你将完成什么

部署一个完整的多层留言板应用：

- 1 副本 **Redis Leader**（处理写请求）
- 2 副本 **Redis Follower**（处理读请求，自动同步 Leader 数据）
- 3 副本 **PHP 前端**（真实留言板页面，向 Leader 写入、向 Follower 读取）
- 各层通过独立的 ClusterIP Service 连通

学完本案例，你将理解：
1. 读写分离架构：写请求走 Leader，读请求走 Follower
2. Redis 主从同步：Follower 自动从 Leader 拉取数据
3. Service 作为"角色路由器"：不同 Service 把流量路由到不同角色的 Pod
4. 多副本 Follower 提升读吞吐量，Leader 保持单点一致写入

## 🏗️ 架构图

```
学生（浏览器）
      │
      ▼
 frontend-svc（ClusterIP :80，LoadBalancer）
      │
  ┌───┴───┐
  │  PHP  │ × 3 副本（gb-frontend:v5）
  └───┬───┘
      │ 写               读
      ▼                  ▼
redis-leader（:6379）  redis-follower（:6379）
      │                  │
 Leader Pod × 1    Follower Pod × 2
      │──────主从同步────▶│
```

## 🐳 使用的镜像

| 镜像 | 角色 | 说明 |
|------|------|------|
| `registry.k8s.io/redis` | Redis Leader | 官方 K8s Redis 镜像 |
| `us-docker.pkg.dev/google-samples/containers/gke/gb-redis-follower:v2` | Redis Follower | 预配置主从同步的 Redis |
| `us-docker.pkg.dev/google-samples/containers/gke/gb-frontend:v5` | PHP 前端 | 真实留言板应用（PHP，读写 Redis） |

> 以上镜像均已预置在本地 registry，首次拉取无需等待。

## ⚠️ 开始前

确认集群就绪：

```bash
kubectl wait --for=condition=Ready node --all --timeout=120s
kubectl get node
```

---

## 🔬 步骤

### Step 1: 部署 Redis Leader

**目标**：部署 1 个 Redis 主节点，负责接收所有写请求，并向 Follower 同步数据。

```bash
kubectl apply -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis-leader
  labels:
    app: redis
    role: leader
    tier: backend
spec:
  replicas: 1
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
        role: leader
        tier: backend
    spec:
      containers:
      - name: leader
        image: "registry.k8s.io/redis@sha256:cb111d1bd870a6a471385a4a69ad17469d326e9dd91e0e455350cacf36e1b3ee"
        resources:
          requests:
            cpu: 100m
            memory: 100Mi
        ports:
        - containerPort: 6379
---
apiVersion: v1
kind: Service
metadata:
  name: redis-leader
  labels:
    app: redis
    role: leader
    tier: backend
spec:
  ports:
  - port: 6379
    targetPort: 6379
  selector:
    app: redis
    role: leader
    tier: backend
EOF
```

**验证**：

```bash
kubectl get pods
kubectl logs -f deployment/redis-leader
```

预期（Pod Running，日志显示 Redis 启动完成）：

```
NAME                            READY   STATUS    RESTARTS   AGE
redis-leader-fb76b4755-xjr2n    1/1     Running   0          11m
```

---

### Step 2: 部署 Redis Follower（2 副本）

**目标**：部署 2 个 Redis 从节点，`gb-redis-follower:v2` 镜像已预配置自动连接 Leader 同步数据。

```bash
kubectl apply -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis-follower
  labels:
    app: redis
    role: follower
    tier: backend
spec:
  replicas: 2
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
        role: follower
        tier: backend
    spec:
      containers:
      - name: follower
        image: us-docker.pkg.dev/google-samples/containers/gke/gb-redis-follower:v2
        resources:
          requests:
            cpu: 100m
            memory: 100Mi
        ports:
        - containerPort: 6379
---
apiVersion: v1
kind: Service
metadata:
  name: redis-follower
  labels:
    app: redis
    role: follower
    tier: backend
spec:
  ports:
  - port: 6379
  selector:
    app: redis
    role: follower
    tier: backend
EOF
```

**验证**：

```bash
kubectl get pods
```

预期（2 个 Follower 都 Running）：

```
NAME                             READY   STATUS    RESTARTS   AGE
redis-follower-dddfbdcc9-82sfr   1/1     Running   0          37s
redis-follower-dddfbdcc9-qrt5k   1/1     Running   0          38s
redis-leader-fb76b4755-xjr2n     1/1     Running   0          11m
```

---

### Step 3: 部署 PHP 前端（3 副本）

**目标**：部署 3 副本的 PHP 留言板前端，通过 DNS 自动发现 Redis Leader 和 Follower Service。

```bash
kubectl apply -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: frontend
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
      - name: php-redis
        image: us-docker.pkg.dev/google-samples/containers/gke/gb-frontend:v5
        resources:
          requests:
            cpu: 100m
            memory: 100Mi
        env:
        - name: GET_HOSTS_FROM
          value: "dns"
        ports:
        - containerPort: 80
---
apiVersion: v1
kind: Service
metadata:
  name: frontend
  labels:
    app: guestbook
    tier: frontend
spec:
  type: LoadBalancer
  ports:
  - port: 80
  selector:
    app: guestbook
    tier: frontend
EOF
```

**关键点**：`GET_HOSTS_FROM: dns` 告诉前端通过 K8s DNS 自动发现 `redis-leader` 和 `redis-follower` Service，无需硬编码 IP。

**验证**：

```bash
kubectl get pods
kubectl get service
```

预期：

```
NAME                        READY   STATUS    RESTARTS   AGE
frontend-85595f5bf9-5tqhf   1/1     Running   0          54s
frontend-85595f5bf9-j2pds   1/1     Running   0          54s
frontend-85595f5bf9-xk2vl   1/1     Running   0          54s

NAME             TYPE           CLUSTER-IP      EXTERNAL-IP   PORT(S)
frontend         LoadBalancer   10.110.187.30   <pending>     80:31345/TCP
redis-follower   ClusterIP      10.110.162.42   <none>        6379/TCP
redis-leader     ClusterIP      10.103.78.24    <none>        6379/TCP
```

---

### Step 4: 访问留言板

由于 K3s 是单节点，LoadBalancer 的 EXTERNAL-IP 为 `<pending>`，用 port-forward 访问：

```bash
kubectl port-forward svc/frontend 8080:80
```

在浏览器访问 `http://localhost:8080`（若在 SSH 终端，用 curl 验证）：

```bash
curl -s http://localhost:8080 | grep -i "guestbook\|留言"
```

预期（返回 PHP 留言板页面 HTML）：

```html
<html ng-app="redis">
  <head>...Guestbook...</head>
  ...
```

留言板界面支持输入留言并提交——写入 Leader，读取 Follower，主从同步在后台完成。

---

### Step 5: 扩容前端

```bash
kubectl scale deployment frontend --replicas=5
kubectl get pods
```

预期（5 个前端 Pod 全部 Running）：

```
NAME                        READY   STATUS    RESTARTS   AGE
frontend-85595f5bf9-5tqhf   1/1     Running   0          6m
frontend-85595f5bf9-j2pds   1/1     Running   0          6m
frontend-85595f5bf9-xk2vl   1/1     Running   0          6m
frontend-85595f5bf9-mnjnf   1/1     Running   0          15s
frontend-85595f5bf9-p9d4k   1/1     Running   0          15s
```

---

## ✅ 验证整体完成

```bash
kubectl get deployment,pod,svc -l app=redis
kubectl get deployment,pod,svc -l app=guestbook
```

预期（全部 READY，3 个 Service 存在）：

```
NAME                           READY   UP-TO-DATE   AVAILABLE
deployment.apps/redis-follower  2/2     2            2
deployment.apps/redis-leader    1/1     1            1
deployment.apps/frontend        3/3     3            3

NAME               TYPE           PORT(S)
frontend           LoadBalancer   80:xxxxx/TCP
redis-follower     ClusterIP      6379/TCP
redis-leader       ClusterIP      6379/TCP
```

---

## 🧹 清理

```bash
kubectl delete deployment redis-leader redis-follower frontend
kubectl delete service redis-leader redis-follower frontend
```

验证清理完成：

```bash
kubectl get pod,svc | grep -E "redis|frontend"
# 预期：无输出
```

---

## 🚀 扩展练习

1. **扩容 Frontend**：`kubectl scale deployment frontend --replicas=5`，再缩回 3
2. **扩容 Follower**：`kubectl scale deployment redis-follower --replicas=4`，留言板读性能进一步提升
3. **验证读写分离**：提交一条留言后，进入 Follower Pod 用 `redis-cli KEYS *` 查看数据是否已同步
