# 案例 D01: 留言板应用（Guestbook）

## 📚 案例信息

- **难度**: ⭐⭐⭐（中级）
- **时长**: 30 分钟
- **环境**: K3s 单节点集群
- **前置**: 已有可用的 K8s 集群（完成实验 1）

## 🎯 你将完成什么

部署一个完整的三层留言板应用：

- 3 副本 `nginx` **前端** Deployment（对外提供页面）
- 1 副本 `redis:7-alpine` **Redis Leader**（处理写请求）
- 2 副本 `redis:7-alpine` **Redis Follower**（处理读请求，自动同步 Leader 数据）
- 各层通过独立的 ClusterIP Service 连通

学完本案例，你将理解：
1. 读写分离架构：写请求走 Leader，读请求走 Follower
2. Redis 主从同步：Follower 用 `--replicaof` 参数自动拉取 Leader 数据
3. Service 作为"角色路由器"：不同 Service 路由到不同角色的 Pod
4. 多副本 Follower 提升读吞吐量，Leader 保持单点一致写入

## 🏗️ 架构图

```
学生（curl / 浏览器）
         │
         ▼
  frontend-svc（ClusterIP :80）
         │
    ┌────┴────┐
    │ nginx   │ × 3 副本（前端）
    └────┬────┘
         │
    写请求│                  读请求
         ▼                     ▼
redis-leader-svc（:6379）  redis-follower-svc（:6379）
         │                     │
    ┌────┴────┐           ┌────┴────┐
    │  Redis  │──主从同步─▶│  Redis  │ × 2 副本
    │ Leader  │           │Follower │
    └─────────┘           └─────────┘
```

**关键设计**：两个 Redis Service 指向不同角色，前端写 Leader、读 Follower，实现读写分离。

## 🐳 使用的镜像

| 镜像 | 角色 | 来源 |
|------|------|------|
| `redis:7-alpine` | Leader（写）+ Follower（读） | 本地 registry mirror |
| `nginx` | 前端 Web 服务器 | 本地 registry mirror |

> 同一个镜像，通过不同的启动参数承担不同角色——这是生产环境中常见的做法。

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
    app: guestbook
    role: leader
spec:
  replicas: 1
  selector:
    matchLabels:
      app: guestbook
      role: leader
  template:
    metadata:
      labels:
        app: guestbook
        role: leader
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
  name: redis-leader-svc
  labels:
    app: guestbook
    role: leader
spec:
  type: ClusterIP
  selector:
    app: guestbook
    role: leader
  ports:
  - port: 6379
    targetPort: 6379
EOF
```

**验证**：

```bash
kubectl wait --for=condition=Available deployment/redis-leader --timeout=60s
kubectl get pod -l role=leader
```

预期输出：

```
NAME                            READY   STATUS    RESTARTS   AGE
redis-leader-xxxxxxxxx-xxxxx    1/1     Running   0          20s
```

---

### Step 2: 部署 Redis Follower（2 副本）

**目标**：部署 2 个 Redis 从节点，通过 `--replicaof` 参数自动向 Leader 发起同步，负责处理读请求。

```bash
kubectl apply -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis-follower
  labels:
    app: guestbook
    role: follower
spec:
  replicas: 2
  selector:
    matchLabels:
      app: guestbook
      role: follower
  template:
    metadata:
      labels:
        app: guestbook
        role: follower
    spec:
      containers:
      - name: redis
        image: redis:7-alpine
        command: ["redis-server", "--replicaof", "redis-leader-svc", "6379"]
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
  name: redis-follower-svc
  labels:
    app: guestbook
    role: follower
spec:
  type: ClusterIP
  selector:
    app: guestbook
    role: follower
  ports:
  - port: 6379
    targetPort: 6379
EOF
```

**验证（Follower 就绪，并与 Leader 建立同步）**：

```bash
kubectl wait --for=condition=Available deployment/redis-follower --timeout=60s
kubectl get pod -l role=follower
```

预期输出（2 个 Follower 都 Running）：

```
NAME                              READY   STATUS    RESTARTS   AGE
redis-follower-xxxxxxxxx-aaaaa    1/1     Running   0          15s
redis-follower-xxxxxxxxx-bbbbb    1/1     Running   0          15s
```

**确认主从同步已建立**：

```bash
FOLLOWER_POD=$(kubectl get pod -l role=follower -o jsonpath='{.items[0].metadata.name}')
kubectl exec $FOLLOWER_POD -- redis-cli INFO replication | grep -E "role|master_host|master_link_status"
```

预期输出（role 为 slave，master_link_status 为 up）：

```
role:slave
master_host:redis-leader-svc
master_link_status:up
```

---

### Step 3: 部署 nginx 前端（3 副本）

**目标**：部署 3 副本前端，并通过 ClusterIP Service 对外提供访问。

```bash
kubectl apply -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: frontend
  labels:
    app: guestbook
    role: frontend
spec:
  replicas: 3
  selector:
    matchLabels:
      app: guestbook
      role: frontend
  template:
    metadata:
      labels:
        app: guestbook
        role: frontend
    spec:
      containers:
      - name: nginx
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
    role: frontend
spec:
  type: ClusterIP
  selector:
    app: guestbook
    role: frontend
  ports:
  - port: 80
    targetPort: 80
EOF
```

**验证（3 个前端 Pod 全部 Running）**：

```bash
kubectl wait --for=condition=Available deployment/frontend --timeout=60s
kubectl get pod -l role=frontend
```

预期输出：

```
NAME                        READY   STATUS    RESTARTS   AGE
frontend-xxxxxxxxx-aaaaa    1/1     Running   0          15s
frontend-xxxxxxxxx-bbbbb    1/1     Running   0          15s
frontend-xxxxxxxxx-ccccc    1/1     Running   0          15s
```

---

### Step 4: 验证读写分离——写 Leader，从 Follower 读到

**目标**：这是本案例的核心验证。向 Leader 写入数据，确认两个 Follower 都能读到，证明主从同步正常工作。

```bash
# 向 Leader 写入数据
LEADER_POD=$(kubectl get pod -l role=leader -o jsonpath='{.items[0].metadata.name}')
kubectl exec $LEADER_POD -- redis-cli SET guestbook:msg1 "Hello from Leader"
kubectl exec $LEADER_POD -- redis-cli SET guestbook:msg2 "K8s is awesome"
```

预期输出：

```
OK
OK
```

**从 Follower 1 读取**：

```bash
FOLLOWER_0=$(kubectl get pod -l role=follower -o jsonpath='{.items[0].metadata.name}')
kubectl exec $FOLLOWER_0 -- redis-cli GET guestbook:msg1
kubectl exec $FOLLOWER_0 -- redis-cli GET guestbook:msg2
```

**从 Follower 2 读取**：

```bash
FOLLOWER_1=$(kubectl get pod -l role=follower -o jsonpath='{.items[1].metadata.name}')
kubectl exec $FOLLOWER_1 -- redis-cli GET guestbook:msg1
kubectl exec $FOLLOWER_1 -- redis-cli GET guestbook:msg2
```

两个 Follower 的预期输出（与写入完全一致）：

```
"Hello from Leader"
"K8s is awesome"
```

**验证 Follower 只读（不接受写入）**：

```bash
kubectl exec $FOLLOWER_0 -- redis-cli SET guestbook:direct "try write to follower"
```

预期输出（从节点拒绝写入）：

```
(error) READONLY You can't write against a read only replica.
```

---

### Step 5: 验证 Service 负载均衡

**目标**：确认 `redis-follower-svc` 把请求分散到两个 Follower Pod。

```bash
# 通过 Service 连续查询，观察请求分布（不同 Pod 处理）
LEADER_POD=$(kubectl get pod -l role=leader -o jsonpath='{.items[0].metadata.name}')
for i in $(seq 1 6); do
  kubectl exec $LEADER_POD -- redis-cli -h redis-follower-svc GET guestbook:msg1
done
```

预期输出（6 次均成功返回，Service 在两个 Follower 之间负载均衡）：

```
"Hello from Leader"
"Hello from Leader"
...（共 6 行）
```

查看两个 Follower 的访问日志，可以看到请求被分散：

```bash
kubectl logs -l role=follower --prefix --tail=5
```

---

### Step 6: 验证架构完整性——一览全局

```bash
kubectl get deployment,pod,svc -l app=guestbook
```

预期输出（全部就绪）：

```
NAME                             READY   UP-TO-DATE   AVAILABLE
deployment.apps/frontend         3/3     3            3
deployment.apps/redis-follower   2/2     2            2
deployment.apps/redis-leader     1/1     1            1

NAME                                  READY   STATUS
pod/frontend-xxx-aaa                  1/1     Running
pod/frontend-xxx-bbb                  1/1     Running
pod/frontend-xxx-ccc                  1/1     Running
pod/redis-follower-xxx-ddd            1/1     Running
pod/redis-follower-xxx-eee            1/1     Running
pod/redis-leader-xxx-fff              1/1     Running

NAME                   TYPE        PORT(S)
frontend-svc           ClusterIP   80/TCP
redis-follower-svc     ClusterIP   6379/TCP
redis-leader-svc       ClusterIP   6379/TCP
```

---

## ✅ 验证整体完成

运行以下检查，全部通过即完成：

```bash
# 1. 主从同步状态
LEADER_POD=$(kubectl get pod -l role=leader -o jsonpath='{.items[0].metadata.name}')
kubectl exec $LEADER_POD -- redis-cli INFO replication | grep connected_slaves

# 2. 数据一致性
FOLLOWER_POD=$(kubectl get pod -l role=follower -o jsonpath='{.items[0].metadata.name}')
kubectl exec $FOLLOWER_POD -- redis-cli GET guestbook:msg1
```

预期输出：

```
connected_slaves:2        ← Leader 已连接 2 个 Follower

"Hello from Leader"       ← Follower 数据与 Leader 一致
```

---

## 🧹 清理

```bash
kubectl delete deployment frontend redis-leader redis-follower
kubectl delete service frontend-svc redis-leader-svc redis-follower-svc
```

验证清理完成：

```bash
kubectl get pod,svc -l app=guestbook
# 预期：No resources found.
```

---

## 🚀 扩展练习

1. **扩容 Follower**：`kubectl scale deployment redis-follower --replicas=4`，观察 Leader 同步到新 Follower 的过程（`INFO replication` 中 connected_slaves 变为 4）
2. **Leader 故障模拟**：删除 Leader Pod，观察 Follower 的 `master_link_status` 变为 `down`，新 Leader Pod 重建后自动恢复同步
3. **写压力测试**：用 `redis-cli --pipe` 向 Leader 批量写入 1000 条数据，随后在 Follower 验证全部同步
4. **哨兵模式**（进阶）：了解 Redis Sentinel 如何在 Leader 故障时自动将 Follower 提升为新 Leader
