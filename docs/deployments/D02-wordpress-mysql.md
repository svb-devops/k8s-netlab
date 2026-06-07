# 案例 D02: 有状态应用——MySQL + 持久化存储

## 📚 案例信息

- **难度**: ⭐⭐⭐⭐（进阶）
- **时长**: 45 分钟
- **环境**: K3s 单节点集群
- **前置**: 已完成 D01（了解 Deployment + Service 基础）

## 🎯 你将完成什么

部署一个带持久化存储的 MySQL 数据库，并验证 Pod 重建后数据不丢失：

- 用 `PersistentVolume` + `PersistentVolumeClaim` 挂载存储，保证数据与 Pod 生命周期解耦
- 部署 MySQL Deployment，使用 `Recreate` 策略（单实例有状态应用的正确策略）
- 通过 Headless Service（`clusterIP: None`）暴露数据库
- 用 MySQL 客户端连接、写入数据，重建 Pod 后验证数据依然存在

学完本案例，你将理解：
1. **为什么有状态应用用 `Recreate` 而非 `RollingUpdate`**：单实例数据库无法同时运行新旧两个 Pod 挂载同一个 PVC
2. **Headless Service**：`clusterIP: None` 使 DNS 直接解析到 Pod IP，适合需要直连 Pod 的有状态应用
3. **PVC 与 Pod 的生命周期解耦**：Pod 删了，数据还在

## 🏗️ 架构图

```
mysql-pv-volume（HostPath PV）
      │
      └──▶ mysql-pv-claim（PVC，20Gi）
                  │
            MySQL Pod（mysql:9）
                  │ 挂载 /var/lib/mysql
         Headless Service（mysql，clusterIP:None）
                  │
             DNS 直解 Pod IP
                  │
            MySQL 客户端（kubectl run）
```

## 🐳 使用的镜像

| 镜像 | 用途 | 来源 |
|------|------|------|
| `mysql:9` | 数据库服务 | 本地 registry mirror |

## ⚠️ 开始前

确认集群就绪，并查看默认 StorageClass：

```bash
kubectl wait --for=condition=Ready node --all --timeout=120s
kubectl get storageclass
```

---

## 🔬 步骤

### Step 1: 创建 PersistentVolume 和 PersistentVolumeClaim

**目标**：手动创建 PV（HostPath 类型），并声明对应的 PVC。

```bash
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: PersistentVolume
metadata:
  name: mysql-pv-volume
  labels:
    type: local
spec:
  storageClassName: manual
  capacity:
    storage: 20Gi
  accessModes:
  - ReadWriteOnce
  hostPath:
    path: "/mnt/data"
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: mysql-pv-claim
spec:
  storageClassName: manual
  accessModes:
  - ReadWriteOnce
  resources:
    requests:
      storage: 20Gi
EOF
```

**验证**：

```bash
kubectl get pv mysql-pv-volume
kubectl get pvc mysql-pv-claim
```

预期（PV 为 Available，PVC 为 Bound 或 Pending 等待 Pod 调度）：

```
NAME              CAPACITY   STATUS      STORAGECLASS
mysql-pv-volume   20Gi       Available   manual

NAME             STATUS    CAPACITY   STORAGECLASS
mysql-pv-claim   Pending              manual
```

---

### Step 2: 部署 MySQL

**目标**：创建 MySQL Deployment 和 Headless Service。

**关键配置说明**：
- `strategy.type: Recreate`：先删旧 Pod，再建新 Pod，避免两个 Pod 同时挂载同一个 PVC
- `clusterIP: None`：Headless Service，DNS 直接解析到 Pod IP（而非 VIP）

```bash
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: Service
metadata:
  name: mysql
spec:
  ports:
  - port: 3306
  selector:
    app: mysql
  clusterIP: None
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mysql
spec:
  selector:
    matchLabels:
      app: mysql
  strategy:
    type: Recreate
  template:
    metadata:
      labels:
        app: mysql
    spec:
      containers:
      - image: mysql:9
        name: mysql
        env:
        - name: MYSQL_ROOT_PASSWORD
          value: password
        ports:
        - containerPort: 3306
          name: mysql
        volumeMounts:
        - name: mysql-persistent-storage
          mountPath: /var/lib/mysql
      volumes:
      - name: mysql-persistent-storage
        persistentVolumeClaim:
          claimName: mysql-pv-claim
EOF
```

**等待 MySQL 就绪**（首次初始化约 60-90 秒）：

```bash
kubectl describe deployment mysql
kubectl get pods -l app=mysql
```

预期输出：

```
NAME                     READY   STATUS    RESTARTS   AGE
mysql-xxxxxxxxx-xxxxx    1/1     Running   0          90s
```

**确认 PVC 已 Bound**：

```bash
kubectl describe pvc mysql-pv-claim
```

---

### Step 3: 连接 MySQL 并写入数据

**目标**：用临时客户端 Pod 通过 Headless Service DNS 名连接 MySQL，写入测试数据。

```bash
kubectl run -it --rm --image=mysql:9 --restart=Never mysql-client -- \
  mysql -h mysql -ppassword
```

进入 MySQL 命令行后，执行：

```sql
CREATE DATABASE IF NOT EXISTS testdb;
USE testdb;
CREATE TABLE messages (
  id INT AUTO_INCREMENT PRIMARY KEY,
  content VARCHAR(255),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO messages (content) VALUES ('Hello from Kubernetes');
INSERT INTO messages (content) VALUES ('Data persists across Pod restarts');
SELECT * FROM messages;
exit
```

预期输出：

```
+----+-----------------------------------+---------------------+
| id | content                           | created_at          |
+----+-----------------------------------+---------------------+
|  1 | Hello from Kubernetes             | 2026-xx-xx xx:xx:xx |
|  2 | Data persists across Pod restarts | 2026-xx-xx xx:xx:xx |
+----+-----------------------------------+---------------------+
```

**关键点**：连接使用的是 Service 名 `mysql`（Headless Service，DNS 解析直接指向 Pod IP）。

---

### Step 4: 验证数据持久化——删除 Pod 后数据依然存在

**目标**：强制删除 Pod，观察 `Recreate` 策略下的重建过程，再验证数据未丢失。

```bash
# 记录当前 Pod
kubectl get pods -l app=mysql

# 删除 Pod（模拟崩溃）
kubectl delete pod -l app=mysql

# 观察重建过程（Recreate：先完全删除，再新建）
kubectl get pods -l app=mysql -w
```

预期过程（Ctrl+C 退出）：

```
NAME                   READY   STATUS        RESTARTS
mysql-xxx-old          1/1     Terminating
mysql-xxx-new          0/1     Pending       → Running
```

**连接新 Pod，查询数据**：

```bash
kubectl run -it --rm --image=mysql:9 --restart=Never mysql-client -- \
  mysql -h mysql -ppassword testdb -e "SELECT * FROM messages;"
```

预期（数据完整保留，与 Step 3 相同）：

```
+----+-----------------------------------+---------------------+
| id | content                           | created_at          |
+----+-----------------------------------+---------------------+
|  1 | Hello from Kubernetes             | 2026-xx-xx xx:xx:xx |
|  2 | Data persists across Pod restarts | 2026-xx-xx xx:xx:xx |
+----+-----------------------------------+---------------------+
```

数据存储在 PVC 绑定的 HostPath `/mnt/data`，与 Pod 生命周期完全解耦。

---

### Step 5: 更新 MySQL（观察 Recreate 策略）

**目标**：触发 Deployment 更新，观察 Recreate 策略与 RollingUpdate 的区别。

```bash
# 触发更新（修改环境变量，让 Deployment 重建 Pod）
kubectl set env deployment/mysql MYSQL_EXTRA_ENV=test

# 立刻观察
kubectl get pods -l app=mysql -w
```

预期（Recreate 策略：旧 Pod 完全停止后，新 Pod 才启动）：

```
NAME               READY   STATUS        
mysql-old-xxx      1/1     Terminating   ← 先停旧 Pod
mysql-new-xxx      0/1     Pending       ← 旧 Pod 完全停止后才开始新 Pod
mysql-new-xxx      1/1     Running
```

**关键对比**：如果是 RollingUpdate，新旧 Pod 会短暂并存——但两个 Pod 同时挂载同一个 ReadWriteOnce PVC 会导致第二个 Pod 启动失败。`Recreate` 正是为避免这个问题而生。

---

## ✅ 验证整体完成

```bash
kubectl get pv mysql-pv-volume
kubectl get pvc mysql-pv-claim
kubectl get deployment mysql
kubectl get svc mysql
```

预期（PV/PVC Bound，Deployment 1/1，Headless Service 无 ClusterIP）：

```
NAME              CAPACITY   STATUS   STORAGECLASS
mysql-pv-volume   20Gi       Bound    manual

NAME             STATUS   CAPACITY
mysql-pv-claim   Bound    20Gi

NAME    READY   UP-TO-DATE   AVAILABLE
mysql   1/1     1            1

NAME    TYPE        CLUSTER-IP   PORT(S)
mysql   ClusterIP   None         3306/TCP
```

---

## 🧹 清理

```bash
kubectl delete deployment,svc mysql
kubectl delete pvc mysql-pv-claim
kubectl delete pv mysql-pv-volume
```

> PV 使用 HostPath，删除 PV 后宿主机目录 `/mnt/data` 仍存在，需手动清理：
> ```bash
> rm -rf /mnt/data
> ```

---

## 🚀 扩展练习

1. **为什么不能 scale？**：尝试 `kubectl scale deployment mysql --replicas=2`，观察第二个 Pod 因 PVC 冲突无法启动
2. **生产最佳实践**：密码改用 Secret（`kubectl create secret generic mysql-pass --from-literal=password=YOUR_PASSWORD`），在 Deployment 中引用
3. **StatefulSet**：把 Deployment 改为 StatefulSet，感受两者在 Pod 命名和 PVC 自动绑定上的区别
