# 案例 D02: 有状态应用——MySQL + 持久化存储

## 📚 案例信息

- **难度**: ⭐⭐⭐⭐（进阶）
- **时长**: 45 分钟
- **环境**: K3s 单节点集群
- **前置**: 已完成 D01（了解 Deployment + Service 基础）

## 🎯 你将完成什么

部署一个带持久化存储的 MySQL 数据库，并验证 Pod 重建后数据不丢失：

- 用 `Secret` 安全存储数据库密码（而非明文写进 YAML）
- 用 `PersistentVolumeClaim` 挂载存储，保证数据与 Pod 生命周期解耦
- 部署 MySQL Deployment，挂载 PVC
- 用 `busybox` 客户端 Pod 连接 MySQL，写入数据、重建 Pod、验证数据依然存在

学完本案例，你将理解：
1. 为什么有状态应用不能像无状态 Pod 一样"重启即恢复"
2. Secret 的使用方式——通过环境变量注入，而非硬编码
3. PVC 与 Pod 的生命周期解耦——Pod 删了，数据还在
4. K3s 的默认 StorageClass（local-path）如何自动分配 PV

## 🏗️ 架构图

```
Secret（db-secret）
    │ 注入环境变量
    ▼
MySQL Pod ──── PVC（mysql-pvc）──── 宿主机本地目录
    │
    ▼（ClusterIP Service）
 mysql-svc
    │
    ▼
busybox Pod（数据库客户端，手动执行 SQL）
```

## 🐳 使用的镜像

| 镜像 | 用途 | 来源 |
|------|------|------|
| `mysql:8.0` | 数据库服务 | 本地 registry mirror |
| `busybox:1.28` | 数据库客户端（mysql 命令行） | 本地 registry mirror |

## ⚠️ 开始前

确认集群就绪，并查看默认 StorageClass：

```bash
kubectl wait --for=condition=Ready node --all --timeout=120s
kubectl get storageclass
```

预期输出（K3s 内置 local-path）：

```
NAME                   PROVISIONER             RECLAIMPOLICY
local-path (default)   rancher.io/local-path   Delete
```

---

## 🔬 步骤

### Step 1: 创建 Secret 存储数据库密码

**目标**：用 Secret 管理敏感信息，不把密码明文写进 Deployment YAML。

```bash
kubectl create secret generic db-secret \
  --from-literal=MYSQL_ROOT_PASSWORD=K8sLab2026 \
  --from-literal=MYSQL_DATABASE=labdb \
  --from-literal=MYSQL_USER=labuser \
  --from-literal=MYSQL_PASSWORD=LabPass2026
```

**验证**（Secret 存储加密，values 不明文显示）：

```bash
kubectl get secret db-secret
kubectl describe secret db-secret
```

预期输出：

```
NAME        TYPE     DATA   AGE
db-secret   Opaque   4      5s

Name:   db-secret
...
Data
====
MYSQL_DATABASE:      5 bytes
MYSQL_PASSWORD:      11 bytes
MYSQL_ROOT_PASSWORD: 10 bytes
MYSQL_USER:          7 bytes
```

---

### Step 2: 创建 PersistentVolumeClaim

**目标**：声明 2Gi 存储，K3s 的 local-path provisioner 自动分配 PV。

```bash
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: mysql-pvc
spec:
  accessModes:
  - ReadWriteOnce
  resources:
    requests:
      storage: 2Gi
EOF
```

**验证**（PVC 初始 Pending，挂载后变 Bound）：

```bash
kubectl get pvc mysql-pvc
```

预期输出（此时还是 Pending，因为 local-path 是懒分配）：

```
NAME        STATUS    VOLUME   CAPACITY   ACCESS MODES   STORAGECLASS
mysql-pvc   Pending                                      local-path
```

> local-path 采用 WaitForFirstConsumer 策略，PVC 在 Pod 调度后才变 Bound。

---

### Step 3: 部署 MySQL

**目标**：创建 MySQL Deployment，引用 Secret 作为环境变量，挂载 PVC 到 `/var/lib/mysql`。

```bash
kubectl apply -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mysql
  labels:
    app: mysql
spec:
  replicas: 1
  selector:
    matchLabels:
      app: mysql
  template:
    metadata:
      labels:
        app: mysql
    spec:
      containers:
      - name: mysql
        image: mysql:8.0
        envFrom:
        - secretRef:
            name: db-secret
        ports:
        - containerPort: 3306
        volumeMounts:
        - name: mysql-storage
          mountPath: /var/lib/mysql
        resources:
          requests:
            cpu: "200m"
            memory: "256Mi"
          limits:
            cpu: "500m"
            memory: "512Mi"
      volumes:
      - name: mysql-storage
        persistentVolumeClaim:
          claimName: mysql-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: mysql-svc
spec:
  type: ClusterIP
  selector:
    app: mysql
  ports:
  - port: 3306
    targetPort: 3306
EOF
```

**等待 MySQL 就绪**（MySQL 首次初始化需要约 60-90 秒）：

```bash
kubectl wait --for=condition=Available deployment/mysql --timeout=120s
kubectl get pod -l app=mysql
```

预期输出：

```
NAME                     READY   STATUS    RESTARTS   AGE
mysql-xxxxxxxxx-xxxxx    1/1     Running   0          90s
```

**同时确认 PVC 已变 Bound**：

```bash
kubectl get pvc mysql-pvc
```

预期输出：

```
NAME        STATUS   VOLUME                                     CAPACITY
mysql-pvc   Bound    pvc-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx   2Gi
```

---

### Step 4: 连接数据库并写入数据

**目标**：用 busybox Pod 作为客户端，连接 MySQL 写入测试数据。

```bash
# 启动临时客户端 Pod
kubectl run mysql-client --image=busybox:1.28 --rm -it --restart=Never -- \
  sh -c '
    # 等待 MySQL 接受连接
    until nc -z mysql-svc 3306; do echo "waiting..."; sleep 2; done
    echo "MySQL is ready"
    
    # 连接并执行 SQL
    # 注意：busybox 没有 mysql 客户端，用 nc 发原始 SQL 验证端口即可
    echo "Port 3306 is reachable on mysql-svc"
  '
```

用 exec 进入正在运行的 MySQL Pod 执行 SQL（更直接）：

```bash
MYSQL_POD=$(kubectl get pod -l app=mysql -o jsonpath='{.items[0].metadata.name}')

# 创建表并插入数据
kubectl exec $MYSQL_POD -- mysql -u labuser -pLabPass2026 labdb -e "
  CREATE TABLE IF NOT EXISTS messages (
    id INT AUTO_INCREMENT PRIMARY KEY,
    content VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  );
  INSERT INTO messages (content) VALUES ('Hello from K8s - record 1');
  INSERT INTO messages (content) VALUES ('Hello from K8s - record 2');
  SELECT * FROM messages;
"
```

预期输出：

```
id  content                     created_at
1   Hello from K8s - record 1   2026-xx-xx xx:xx:xx
2   Hello from K8s - record 2   2026-xx-xx xx:xx:xx
```

---

### Step 5: 验证数据持久化——删除 Pod 后数据依然存在

**目标**：这是本案例的核心验证——强制删除 Pod，Deployment 重建后，PVC 中的数据是否还在。

```bash
# 记录当前 Pod 名称
OLD_POD=$(kubectl get pod -l app=mysql -o jsonpath='{.items[0].metadata.name}')
echo "删除前 Pod: $OLD_POD"

# 强制删除 Pod（模拟节点故障/Pod 崩溃）
kubectl delete pod $OLD_POD

# 等待新 Pod 启动
echo "等待新 Pod 就绪..."
kubectl wait --for=condition=Available deployment/mysql --timeout=120s

# 新 Pod 名称
NEW_POD=$(kubectl get pod -l app=mysql -o jsonpath='{.items[0].metadata.name}')
echo "新 Pod: $NEW_POD"
```

**查询数据**（确认数据未丢失）：

```bash
kubectl exec $NEW_POD -- mysql -u labuser -pLabPass2026 labdb -e "SELECT * FROM messages;"
```

预期输出（与 Step 4 相同）：

```
id  content                     created_at
1   Hello from K8s - record 1   2026-xx-xx xx:xx:xx
2   Hello from K8s - record 2   2026-xx-xx xx:xx:xx
```

**关键点**：数据存储在 PVC 对应的宿主机目录，与 Pod 生命周期完全解耦。Pod 被删除、重建，数据不受影响。

---

### Step 6: 查看 PV 实际存储位置

**目标**：了解 local-path provisioner 在宿主机的实际存储位置。

```bash
# 查看 PV 详情
kubectl get pv -o wide

# 查看具体存储路径（在 PV 的 spec.local 或 hostPath 中）
PV_NAME=$(kubectl get pvc mysql-pvc -o jsonpath='{.spec.volumeName}')
kubectl describe pv $PV_NAME | grep -A5 "Source"
```

预期输出（local-path 挂载到宿主机某个临时目录）：

```
Source:
    Type:          HostPath (bare host directory volume)
    Path:          /var/lib/rancher/k3s/storage/pvc-xxxxxxxx.../
    HostPathType:  DirectoryOrCreate
```

---

## ✅ 验证整体完成

```bash
kubectl get secret db-secret
kubectl get pvc mysql-pvc
kubectl get deployment mysql
kubectl get svc mysql-svc
```

预期输出（全部就绪）：

```
NAME        TYPE     DATA
db-secret   Opaque   4

NAME        STATUS   CAPACITY
mysql-pvc   Bound    2Gi

NAME    READY   UP-TO-DATE   AVAILABLE
mysql   1/1     1            1

NAME        TYPE        PORT(S)
mysql-svc   ClusterIP   3306/TCP
```

---

## 🧹 清理

```bash
kubectl delete deployment mysql
kubectl delete svc mysql-svc
kubectl delete pvc mysql-pvc
kubectl delete secret db-secret
```

> PVC 删除后，local-path 的 ReclaimPolicy 为 `Delete`，宿主机目录也会被自动清理。

验证清理完成：

```bash
kubectl get pod,pvc,secret | grep -E "mysql|db-secret"
# 预期：无输出
```

---

## 🚀 扩展练习

1. **StatefulSet vs Deployment**：把 mysql Deployment 改为 StatefulSet，观察 Pod 命名（`mysql-0`）和 PVC 自动绑定的区别
2. **ConfigMap 配置注入**：把 MySQL 配置文件（my.cnf）用 ConfigMap 挂载到 `/etc/mysql/conf.d/`
3. **数据库备份**：用 CronJob 定期 `mysqldump` 并存到另一个 PVC（与 D04 结合）
4. **存储容量**：尝试把 `storage: 2Gi` 改为 `200Mi`，插入大量数据，观察写满后的行为
