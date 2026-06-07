# 案例 D05: 多命名空间微服务隔离

## 📚 案例信息

- **难度**: ⭐⭐⭐⭐（进阶）
- **时长**: 40 分钟
- **环境**: K3s 单节点集群
- **前置**: 已完成 D01（Service 和 DNS 基础）

## 🎯 你将完成什么

在同一个 K8s 集群中创建两个独立的团队命名空间，模拟微服务多租户隔离：

- 创建 `team-alpha` 和 `team-beta` 两个命名空间
- 各自部署 nginx 服务，互相独立
- 演示跨命名空间的 DNS 访问格式
- 用 `NetworkPolicy` 限制命名空间间的通信
- 用 `ResourceQuota` 限制命名空间的资源用量

学完本案例，你将理解：
1. Namespace 是 K8s 的逻辑隔离边界——同名资源在不同 namespace 中互不干扰
2. 跨 namespace 访问的 DNS 格式：`<service>.<namespace>.svc.cluster.local`
3. NetworkPolicy 如何在网络层实现命名空间隔离
4. ResourceQuota 如何在资源层限制命名空间的用量

## 🏗️ 架构图

```
cluster.local
├── namespace: team-alpha
│       └── alpha-svc（ClusterIP）→ nginx Pod（"Alpha Team"）
│
├── namespace: team-beta
│       └── beta-svc（ClusterIP）→ nginx Pod（"Beta Team"）
│
└── namespace: default
        └── test-client Pod（busybox，跨 namespace 访问两个服务）
```

**NetworkPolicy 效果**（Step 5 后）：

```
team-alpha Pod ──不能访问──▶ team-beta Pod
team-beta  Pod ──不能访问──▶ team-alpha Pod
default    Pod ──可以访问──▶ 两个 namespace（演示用）
```

## 🐳 使用的镜像

| 镜像 | 用途 | 来源 |
|------|------|------|
| `nginx` | 各团队的 Web 服务 | 本地 registry mirror |
| `busybox:1.28` | 跨 namespace 网络测试客户端 | 本地 registry mirror |

## ⚠️ 开始前

确认集群就绪，并查看当前所有命名空间：

```bash
kubectl wait --for=condition=Ready node --all --timeout=120s
kubectl get namespace
```

预期（K3s 默认命名空间）：

```
NAME              STATUS   AGE
default           Active   ...
kube-system       Active   ...
kube-public       Active   ...
kube-node-lease   Active   ...
```

---

## 🔬 步骤

### Step 1: 创建两个团队命名空间

**目标**：创建 `team-alpha` 和 `team-beta` 命名空间，并加上标签（NetworkPolicy 会用到）。

```bash
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: Namespace
metadata:
  name: team-alpha
  labels:
    team: alpha
    env: lab
---
apiVersion: v1
kind: Namespace
metadata:
  name: team-beta
  labels:
    team: beta
    env: lab
EOF

kubectl get namespace team-alpha team-beta
```

预期输出：

```
NAME         STATUS   AGE
team-alpha   Active   5s
team-beta    Active   5s
```

---

### Step 2: 在各命名空间部署 nginx 服务

**目标**：两个命名空间各有一个 nginx，返回不同的页面内容以便区分。

```bash
# team-alpha：部署 nginx，自定义首页
kubectl apply -n team-alpha -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: alpha-web
spec:
  replicas: 2
  selector:
    matchLabels:
      app: alpha-web
  template:
    metadata:
      labels:
        app: alpha-web
    spec:
      containers:
      - name: nginx
        image: nginx
        ports:
        - containerPort: 80
        command: ["/bin/sh", "-c"]
        args:
        - |
          echo "<h1>Alpha Team Service</h1><p>namespace: team-alpha</p>" > /usr/share/nginx/html/index.html
          nginx -g 'daemon off;'
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
  name: alpha-svc
spec:
  type: ClusterIP
  selector:
    app: alpha-web
  ports:
  - port: 80
    targetPort: 80
EOF

# team-beta：同样部署 nginx，不同首页
kubectl apply -n team-beta -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: beta-web
spec:
  replicas: 2
  selector:
    matchLabels:
      app: beta-web
  template:
    metadata:
      labels:
        app: beta-web
    spec:
      containers:
      - name: nginx
        image: nginx
        ports:
        - containerPort: 80
        command: ["/bin/sh", "-c"]
        args:
        - |
          echo "<h1>Beta Team Service</h1><p>namespace: team-beta</p>" > /usr/share/nginx/html/index.html
          nginx -g 'daemon off;'
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
  name: beta-svc
spec:
  type: ClusterIP
  selector:
    app: beta-web
  ports:
  - port: 80
    targetPort: 80
EOF
```

**验证**：

```bash
kubectl wait --for=condition=Available deployment/alpha-web -n team-alpha --timeout=60s
kubectl wait --for=condition=Available deployment/beta-web -n team-beta --timeout=60s
kubectl get pod,svc -n team-alpha
kubectl get pod,svc -n team-beta
```

预期（两个 namespace 各有 2 个 Pod 和 1 个 Service）：

```
# team-alpha
NAME                            READY   STATUS    ...
pod/alpha-web-xxxxxxxxx-aaaa   1/1     Running
pod/alpha-web-xxxxxxxxx-bbbb   1/1     Running

NAME            TYPE        PORT(S)
service/alpha-svc   ClusterIP   80/TCP

# team-beta（同样格式）
```

---

### Step 3: 演示跨命名空间 DNS 访问

**目标**：从 `default` namespace 的测试 Pod，分别访问两个不同命名空间的服务，观察 DNS 格式差异。

```bash
# 创建测试客户端（在 default namespace）
kubectl run test-client --image=busybox:1.28 --rm -it --restart=Never -- sh
```

进入 shell 后，执行：

```bash
# 在同一 namespace 内，短名访问（default 中没有 alpha-svc）
wget -qO- http://alpha-svc 2>&1 | head -3
# 预期失败：nslookup: can't resolve 'alpha-svc'

# 跨 namespace 访问必须用全限定名
wget -qO- http://alpha-svc.team-alpha.svc.cluster.local
# 预期输出：<h1>Alpha Team Service</h1>...

wget -qO- http://beta-svc.team-beta.svc.cluster.local
# 预期输出：<h1>Beta Team Service</h1>...

# 也可以用简短的跨 namespace 格式（省略 .svc.cluster.local）
wget -qO- http://alpha-svc.team-alpha
# 预期：同样成功

exit
```

**关键点**：
- 同 namespace 内：`http://alpha-svc`（短名）
- 跨 namespace：`http://alpha-svc.team-alpha`（或完整 FQDN）
- `<service>.<namespace>.svc.cluster.local` 是 K8s DNS 的完整格式

---

### Step 4: 验证同名资源隔离

**目标**：在两个 namespace 中创建同名的 ConfigMap，证明它们互不影响。

```bash
# 两个 namespace 各有一个同名 ConfigMap
kubectl create configmap team-config \
  --from-literal=team_name="Alpha Team" \
  --from-literal=max_users="50" \
  -n team-alpha

kubectl create configmap team-config \
  --from-literal=team_name="Beta Team" \
  --from-literal=max_users="30" \
  -n team-beta

# 查看各自的值（互不干扰）
echo "=== team-alpha 的 team-config ==="
kubectl get configmap team-config -n team-alpha -o jsonpath='{.data}' && echo

echo "=== team-beta 的 team-config ==="
kubectl get configmap team-config -n team-beta -o jsonpath='{.data}' && echo
```

预期输出：

```
=== team-alpha 的 team-config ===
{"max_users":"50","team_name":"Alpha Team"}

=== team-beta 的 team-config ===
{"max_users":"30","team_name":"Beta Team"}
```

两个 `team-config` 同名，但属于不同 namespace，完全独立。

---

### Step 5: 用 NetworkPolicy 限制命名空间间访问

**目标**：给 team-alpha 加 NetworkPolicy，拒绝来自 team-beta 的流量。

```bash
kubectl apply -n team-alpha -f - <<'EOF'
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-from-beta
spec:
  podSelector: {}          # 应用到 team-alpha 所有 Pod
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchExpressions:
        - key: team
          operator: NotIn
          values: ["beta"]
EOF
```

**测试 NetworkPolicy 效果**：

```bash
# 从 team-beta 的 Pod 尝试访问 team-alpha（应该被阻止）
BETA_POD=$(kubectl get pod -n team-beta -l app=beta-web -o jsonpath='{.items[0].metadata.name}')

kubectl exec -n team-beta $BETA_POD -- \
  wget -qO- --timeout=5 http://alpha-svc.team-alpha.svc.cluster.local 2>&1
```

预期输出（连接超时，NetworkPolicy 生效）：

```
wget: download timed out
```

```bash
# 从 default namespace 访问 team-alpha（未被限制，应该成功）
kubectl run verify-access --image=busybox:1.28 --rm -it --restart=Never -- \
  wget -qO- --timeout=5 http://alpha-svc.team-alpha.svc.cluster.local
```

预期输出（成功）：

```
<h1>Alpha Team Service</h1><p>namespace: team-alpha</p>
```

---

### Step 6: 设置 ResourceQuota 限制命名空间资源

**目标**：给 team-beta 设置资源配额，防止单个团队消耗过多集群资源。

```bash
kubectl apply -n team-beta -f - <<'EOF'
apiVersion: v1
kind: ResourceQuota
metadata:
  name: beta-quota
spec:
  hard:
    pods: "5"
    requests.cpu: "500m"
    requests.memory: "512Mi"
    limits.cpu: "1"
    limits.memory: "1Gi"
EOF

# 查看配额使用情况
kubectl describe resourcequota beta-quota -n team-beta
```

预期输出（显示当前使用量 vs 配额上限）：

```
Name:            beta-quota
Namespace:       team-beta
Resource         Used    Hard
--------         ----    ----
limits.cpu       400m    1
limits.memory    256Mi   1Gi
pods             2       5
requests.cpu     100m    500m
requests.memory  128Mi   512Mi
```

**测试配额约束**：尝试扩缩到超出配额的副本数：

```bash
# 尝试扩容到 10 副本（会超过 pods: 5 的限制）
kubectl scale deployment beta-web --replicas=10 -n team-beta
kubectl get pod -n team-beta
```

预期（只创建了 5 个 Pod，超出部分被 quota 拒绝）：

```
NAME                        READY   STATUS    RESTARTS
beta-web-xxxxxxxxx-aaaa     1/1     Running
beta-web-xxxxxxxxx-bbbb     1/1     Running
...（最多 5 个）
```

```bash
# 查看 ReplicaSet 事件，可以看到 quota 拒绝信息
kubectl describe replicaset -n team-beta | grep -A5 "Warning"
```

---

## ✅ 验证整体完成

```bash
# 列出所有相关资源
kubectl get namespace team-alpha team-beta
kubectl get deploy,svc -n team-alpha
kubectl get deploy,svc -n team-beta
kubectl get networkpolicy -n team-alpha
kubectl get resourcequota -n team-beta
```

预期（全部资源正常）：

```
NAME         STATUS
team-alpha   Active
team-beta    Active

# team-alpha：alpha-web Deployment + alpha-svc + deny-from-beta NetworkPolicy
# team-beta：beta-web Deployment + beta-svc + beta-quota ResourceQuota
```

---

## 🧹 清理

```bash
# 删除整个 namespace 会同时删除其中所有资源
kubectl delete namespace team-alpha team-beta

# 验证
kubectl get namespace | grep team
# 预期：无输出
```

---

## 🚀 扩展练习

1. **双向隔离**：给 team-beta 也加 NetworkPolicy，实现 alpha 和 beta 互相隔离，但都允许来自 `default` namespace 的访问
2. **LimitRange**：在 namespace 中创建 `LimitRange`，为没有设置 `resources` 的 Pod 自动注入默认限制
3. **跨 namespace Service 访问**：在 team-alpha 部署数据库，team-beta 通过 FQDN 访问（无 NetworkPolicy 限制时）
4. **RBAC 配合**：创建只有读权限的 ServiceAccount，用 `kubectl auth can-i` 验证权限边界（进阶）
