# 案例 D05: 多命名空间微服务隔离

## 📚 案例信息

- **难度**: ⭐⭐⭐⭐（进阶）
- **时长**: 40 分钟
- **环境**: K3s 单节点集群
- **前置**: 已完成 D01（了解 Deployment + Service 基础）

## 🎯 你将完成什么

在同一个 K8s 集群中创建 `development` 和 `production` 两个命名空间，演示命名空间隔离机制：

- 用 `kubectl config set-context` 配置 namespace 专属上下文
- 在不同 namespace 部署同名资源，验证互不干扰
- 通过切换 context 体验"视野"的变化——在 prod context 下看不到 dev 资源
- 理解 namespace 作为 K8s 多租户隔离的核心机制

学完本案例，你将理解：
1. Namespace 是 K8s 的逻辑隔离边界——同名资源在不同 namespace 中互不干扰
2. kubectl context 的 namespace 字段——切换上下文即切换工作命名空间
3. 为什么生产环境必须将 dev/staging/prod 放在不同 namespace（或集群）

## 🏗️ 架构图

```
cluster.local
├── namespace: development
│       └── snowflake Deployment（2 副本）
│
└── namespace: production
        └── cattle Deployment（5 副本）

kubectl context:
  dev  → 操作 development namespace
  prod → 操作 production namespace
```

## 🐳 使用的镜像

| 镜像 | 用途 | 说明 |
|------|------|------|
| `registry.k8s.io/serve_hostname` | 响应 HTTP 请求时返回 Pod 主机名 | 官方 K8s 测试镜像 |

## ⚠️ 开始前

确认集群就绪，查看当前默认命名空间：

```bash
kubectl wait --for=condition=Ready node --all --timeout=120s
kubectl get namespaces
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

### Step 1: 创建 development 和 production 命名空间

```bash
kubectl create -f - <<'EOF'
apiVersion: v1
kind: Namespace
metadata:
  name: development
  labels:
    name: development
EOF

kubectl create -f - <<'EOF'
apiVersion: v1
kind: Namespace
metadata:
  name: production
  labels:
    name: production
EOF
```

**验证**：

```bash
kubectl get namespaces --show-labels
```

预期输出：

```
NAME          STATUS    AGE       LABELS
default       Active    32m       <none>
development   Active    29s       name=development
production    Active    23s       name=production
```

---

### Step 2: 配置 kubectl context

**目标**：为两个 namespace 分别创建 kubectl context，切换 context 就切换工作命名空间。

```bash
# 查看当前集群名和用户名
kubectl config view | grep -E "cluster:|user:" | head -4

# 配置 dev context（根据实际集群名和用户名替换占位符）
CLUSTER=$(kubectl config view -o jsonpath='{.clusters[0].name}')
USER=$(kubectl config view -o jsonpath='{.users[0].name}')

kubectl config set-context dev \
  --namespace=development \
  --cluster=$CLUSTER \
  --user=$USER

kubectl config set-context prod \
  --namespace=production \
  --cluster=$CLUSTER \
  --user=$USER

# 查看已配置的 context
kubectl config view
```

预期（config 中出现 dev 和 prod context）：

```
contexts:
- context:
    cluster: default
    namespace: development
    user: default
  name: dev
- context:
    cluster: default
    namespace: production
    user: default
  name: prod
```

---

### Step 3: 在 development namespace 部署应用

**目标**：切换到 dev context，部署 2 副本的 snowflake 应用。

```bash
# 切换到 dev context
kubectl config use-context dev
kubectl config current-context
```

预期输出：`dev`

```bash
kubectl apply -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  labels:
    app: snowflake
  name: snowflake
spec:
  replicas: 2
  selector:
    matchLabels:
      app: snowflake
  template:
    metadata:
      labels:
        app: snowflake
    spec:
      containers:
      - image: registry.k8s.io/serve_hostname
        imagePullPolicy: Always
        name: snowflake
EOF
```

**验证**（在 dev context 下，直接 `get` 即操作 development namespace）：

```bash
kubectl get deployment
kubectl get pods -l app=snowflake
```

预期输出：

```
NAME         READY   UP-TO-DATE   AVAILABLE   AGE
snowflake    2/2     2            2           2m

NAME                         READY   STATUS    RESTARTS   AGE
snowflake-3968820950-9dgr8   1/1     Running   0          2m
snowflake-3968820950-vgc4n   1/1     Running   0          2m
```

---

### Step 4: 在 production namespace 部署应用

**目标**：切换到 prod context，部署 5 副本的 cattle 应用，验证与 development 完全隔离。

```bash
# 切换到 prod context
kubectl config use-context prod

# 验证切换成功（dev 的资源看不见了）
kubectl get deployment
```

预期输出（production namespace 中没有任何 Deployment）：

```
No resources found in production namespace.
```

```bash
# 在 production 部署 cattle
kubectl create deployment cattle \
  --image=registry.k8s.io/serve_hostname \
  --replicas=5

kubectl get deployment
kubectl get pods -l app=cattle
```

预期输出：

```
NAME     READY   UP-TO-DATE   AVAILABLE   AGE
cattle   5/5     5            5           10s

NAME                      READY   STATUS    RESTARTS   AGE
cattle-2263376956-41xy6   1/1     Running   0          34s
cattle-2263376956-kw466   1/1     Running   0          34s
cattle-2263376956-n4v97   1/1     Running   0          34s
cattle-2263376956-p5p3i   1/1     Running   0          34s
cattle-2263376956-sxpth   1/1     Running   0          34s
```

---

### Step 5: 验证命名空间隔离

**目标**：反复切换 context，观察"视野"随之切换——每个 context 只看到自己 namespace 的资源。

```bash
# 切回 dev，只看到 snowflake
kubectl config use-context dev
kubectl get all

# 切到 prod，只看到 cattle
kubectl config use-context prod
kubectl get all
```

**跨 namespace 查看**（需要加 `-n` 或 `--all-namespaces`）：

```bash
# 切回 dev context，用 -n 查看 production 的资源
kubectl config use-context dev
kubectl get deployment -n production

# 查看所有 namespace 的 Pod
kubectl get pods --all-namespaces | grep -E "snowflake|cattle"
```

预期输出：

```
# -n production 下看到 cattle
NAME     READY   UP-TO-DATE   AVAILABLE
cattle   5/5     5            5

# --all-namespaces 下两者并列
NAMESPACE     NAME                       READY   STATUS
development   snowflake-xxx-aaaa         1/1     Running
development   snowflake-xxx-bbbb         1/1     Running
production    cattle-xxx-cccc            1/1     Running
...（5 个 cattle pod）
```

---

### Step 6: 同名资源在不同 namespace 互不干扰

**目标**：在 production namespace 也创建一个叫 `snowflake` 的 Deployment，验证与 development 中的同名 Deployment 完全独立。

```bash
kubectl config use-context prod

kubectl create deployment snowflake \
  --image=registry.k8s.io/serve_hostname \
  --replicas=3

# 两个 namespace 各自有自己的 snowflake
kubectl get deployment -n development snowflake
kubectl get deployment -n production snowflake
```

预期（同名 Deployment，副本数不同，互不影响）：

```
# development 的 snowflake
NAME        READY   UP-TO-DATE   AVAILABLE
snowflake   2/2     2            2

# production 的 snowflake
NAME        READY   UP-TO-DATE   AVAILABLE
snowflake   3/3     3            3
```

---

## ✅ 验证整体完成

```bash
kubectl get namespaces development production
kubectl get deployment -n development
kubectl get deployment -n production
```

预期：

```
NAME          STATUS   AGE
development   Active   15m
production    Active   15m

# development
NAME        READY
snowflake   2/2

# production
NAME        READY
cattle      5/5
snowflake   3/3
```

---

## 🧹 清理

```bash
# 删除 namespace 会同时删除其中所有资源
kubectl delete namespace development production

# 删除临时 context
kubectl config delete-context dev
kubectl config delete-context prod

# 切回 default context
kubectl config use-context default 2>/dev/null || true
```

验证：

```bash
kubectl get namespace | grep -E "development|production"
# 预期：无输出
```

---

## 🚀 扩展练习

1. **ResourceQuota**：给 `development` namespace 加资源配额，限制最多 5 个 Pod 和 1 CPU
2. **LimitRange**：给 namespace 设置默认资源请求/限制，让没有写 `resources` 的 Pod 自动获得默认值
3. **RBAC**：创建只能操作 development namespace 的 ServiceAccount，验证它无法看到 production 资源
4. **NetworkPolicy**：禁止跨 namespace 的 Pod 间通信，实现真正的网络层隔离
