# 实验9: StatefulSet有状态应用管理

## 📋 实验信息

- **难度**: ⭐⭐⭐⭐ (中高级)
- **时长**: 45-50分钟
- **环境**: K3s单节点集群
- **前置**: 完成实验6-7，理解Service和PV/PVC

## 🎯 学习目标

通过本实验，你将：
1. 理解StatefulSet与Deployment的本质区别
2. 掌握有状态应用的三大特性（网络、存储、顺序）
3. 学习稳定的网络标识和DNS解析
4. 理解每个Pod独立的持久化存储
5. 掌握有序部署、扩容、缩容机制
6. 学习Headless Service的配置和使用
7. 理解实际应用场景（数据库、消息队列、分布式协调）

## 📚 前置知识

- 完成实验6（DNS服务发现）
- 完成实验7（持久化存储）
- 理解Service的作用
- 理解PV/PVC机制
- 了解有状态应用需求

---

## 🐳 实验镜像说明

本实验使用的镜像：

### nginx
- **用途**: 演示有状态应用特性
- **场景**: 每个Pod独立的Web服务器
- **特点**: 简单、易于验证

### busybox:1.28
- **用途**: DNS查询和网络验证
- **场景**: 验证稳定网络标识

**💡 StatefulSet实验特点:**
- 演示Pod的唯一标识
- 验证独立的持久化存储
- 观察有序部署过程
- 理解有状态应用管理

**📖 关于StatefulSet:**
- 无状态应用用Deployment，有状态应用用StatefulSet
- 每个Pod有固定名称（web-0, web-1）
- 必须配合Headless Service使用
- volumeClaimTemplates为每个Pod创建独立PVC

---

## ⚠️ 开始实验前

VM刚启动时，K3s需要约2-3分钟完成初始化。请先确认环境就绪：

```bash
# 等待节点Ready
kubectl wait --for=condition=Ready node --all --timeout=180s

# 确认系统Pod运行正常
kubectl get pod -n kube-system

# 确认StorageClass可用（StatefulSet需要）
kubectl get storageclass
```

**预期结果:**
- 节点Ready
- 系统Pod大部分Running
- local-path StorageClass存在

如果看到节点NotReady或大量Pod处于Pending，请等待2-3分钟再继续。

---

## 🚀 实验步骤

### Step 1: 对比Deployment和StatefulSet

**开始前快速检查:**

```bash
# 确认环境就绪
kubectl get node
kubectl get storageclass
```

**先创建普通Deployment观察Pod命名:**

```bash
# 创建Deployment
kubectl create deployment nginx-deploy --image=nginx --replicas=3

# 等待Pod运行
kubectl wait --for=condition=Ready pod -l app=nginx-deploy --timeout=120s

# 观察Pod名称（随机后缀）
kubectl get pod -l app=nginx-deploy
```

**预期输出:**
```
NAME                            READY   STATUS    RESTARTS
nginx-deploy-7d6d8c84f5-abcde   1/1     Running   0
nginx-deploy-7d6d8c84f5-fghij   1/1     Running   0
nginx-deploy-7d6d8c84f5-klmno   1/1     Running   0
```

**删除一个Pod，观察重建:**

```bash
# 记录一个Pod名称
POD_NAME=$(kubectl get pod -l app=nginx-deploy -o jsonpath='{.items[0].metadata.name}')
echo "删除Pod: $POD_NAME"

# 删除Pod
kubectl delete pod $POD_NAME

# 观察重建后的名称（变了！）
kubectl get pod -l app=nginx-deploy
```

**清理:**

```bash
kubectl delete deployment nginx-deploy
```

**💡 知识点:**
- Deployment的Pod名称包含随机字符串
- 重建后名称不同，网络标识不稳定
- Pod之间完全可互换，适合无状态应用
- 适用场景：Web服务、API、微服务

---

### Step 2: 创建Headless Service

StatefulSet必须配合Headless Service使用，为每个Pod提供稳定DNS记录：

```bash
cat > headless-service.yaml <<EOF
apiVersion: v1
kind: Service
metadata:
  name: nginx
  labels:
    app: nginx
spec:
  clusterIP: None   # 这就是Headless Service的关键
  selector:
    app: nginx
  ports:
  - port: 80
    name: web
EOF

# 应用Service
kubectl apply -f headless-service.yaml

# 查看Service（注意ClusterIP是None）
kubectl get svc nginx
kubectl describe svc nginx
```

**预期输出:**
```
NAME    TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)   AGE
nginx   ClusterIP   None         <none>        80/TCP    5s
```

**验证点:** ✅ Headless Service创建成功，ClusterIP为None

**💡 知识点:**
- `clusterIP: None` 定义Headless Service
- 不分配ClusterIP，不做负载均衡
- DNS直接返回Pod IP列表
- StatefulSet必须使用Headless Service
- 为每个Pod提供独立的DNS A记录

---

### Step 3: 创建StatefulSet

```bash
cat > statefulset.yaml <<EOF
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: web
spec:
  serviceName: "nginx"       # 关联Headless Service
  replicas: 3
  selector:
    matchLabels:
      app: nginx
  template:
    metadata:
      labels:
        app: nginx
    spec:
      containers:
      - name: nginx
        image: nginx
        ports:
        - containerPort: 80
          name: web
        volumeMounts:
        - name: www
          mountPath: /usr/share/nginx/html
  volumeClaimTemplates:      # 为每个Pod自动创建PVC
  - metadata:
      name: www
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: "local-path"
      resources:
        requests:
          storage: 1Gi
EOF

# 应用StatefulSet
kubectl apply -f statefulset.yaml

# 观察Pod有序创建过程
kubectl get pod -l app=nginx -w
```

**预期输出（有序创建）:**
```
NAME    READY   STATUS              RESTARTS
web-0   0/1     ContainerCreating   0
web-0   1/1     Running             0        ← web-0就绪后才创建web-1
web-1   0/1     ContainerCreating   0
web-1   1/1     Running             0        ← web-1就绪后才创建web-2
web-2   0/1     ContainerCreating   0
web-2   1/1     Running             0
```

按 `Ctrl+C` 退出watch，然后继续验证：

```bash
# 查看Pod（名称固定：web-0, web-1, web-2）
kubectl get pod -l app=nginx

# 查看自动创建的PVC
kubectl get pvc

# 查看StatefulSet状态
kubectl get statefulset web
```

**预期PVC输出:**
```
NAME        STATUS   VOLUME          CAPACITY   STORAGECLASS
www-web-0   Bound    pvc-xxxxx...    1Gi        local-path
www-web-1   Bound    pvc-yyyyy...    1Gi        local-path
www-web-2   Bound    pvc-zzzzz...    1Gi        local-path
```

**验证点:** ✅ Pod有序创建（0→1→2），名称固定，PVC自动创建

**💡 知识点:**
- Pod名称格式：`<statefulset-name>-<ordinal>`
- ordinal从0开始递增
- 有序创建：前一个Pod Ready后才创建下一个
- `serviceName` 关联Headless Service
- `volumeClaimTemplates` 为每个Pod创建独立PVC
- PVC命名：`<pvc-name>-<pod-name>`，如 `www-web-0`

---

### Step 4: 验证稳定的网络标识

```bash
# 等待所有Pod就绪
kubectl wait --for=condition=Ready pod -l app=nginx --timeout=180s

# 查看Pod IP
kubectl get pod -l app=nginx -o wide

# 使用busybox验证DNS解析
kubectl run dns-test --image=busybox:1.28 --rm -it --restart=Never -- sh -c "
  echo '=== 验证每个Pod的DNS ==='
  nslookup web-0.nginx.default.svc.cluster.local
  echo '---'
  nslookup web-1.nginx.default.svc.cluster.local
  echo '---'
  nslookup web-2.nginx.default.svc.cluster.local
"
```

**预期输出:**
```
=== 验证每个Pod的DNS ===
Server:    10.43.0.10
Address 1: 10.43.0.10 kube-dns.kube-system.svc.cluster.local

Name:      web-0.nginx.default.svc.cluster.local
Address 1: 10.42.0.x   ← 直接返回Pod IP

Name:      web-1.nginx.default.svc.cluster.local
Address 1: 10.42.0.y

Name:      web-2.nginx.default.svc.cluster.local
Address 1: 10.42.0.z
```

**对比Headless Service的DNS（返回所有Pod IP）:**

```bash
kubectl run dns-test2 --image=busybox:1.28 --rm -it --restart=Never -- nslookup nginx.default.svc.cluster.local
```

**预期输出:**
```
Name:      nginx.default.svc.cluster.local
Address 1: 10.42.0.x   ← 返回所有Pod的IP
Address 2: 10.42.0.y
Address 3: 10.42.0.z
```

**删除Pod后验证DNS不变:**

```bash
# 记录web-1的IP
kubectl get pod web-1 -o wide

# 删除web-1
kubectl delete pod web-1

# 等待重建
kubectl wait --for=condition=Ready pod/web-1 --timeout=120s

# 再次查看IP（IP可能变，但DNS不变）
kubectl get pod web-1 -o wide

# DNS名称始终不变
kubectl run dns-test3 --image=busybox:1.28 --rm -it --restart=Never -- nslookup web-1.nginx.default.svc.cluster.local
```

**验证点:** ✅ 每个Pod有稳定DNS名称，重建后DNS不变

**💡 知识点:**
- Pod DNS格式：`<pod-name>.<service-name>.<namespace>.svc.cluster.local`
- 即使Pod重建，DNS名称不变
- IP可能变化，但DNS始终解析到正确Pod
- 这是有状态应用的关键特性
- 数据库主从可以通过DNS互相发现

---

### Step 5: 验证每个Pod的独立存储

```bash
# 向每个Pod写入不同数据
kubectl exec web-0 -- sh -c "echo 'Hello from web-0' > /usr/share/nginx/html/index.html"
kubectl exec web-1 -- sh -c "echo 'Hello from web-1' > /usr/share/nginx/html/index.html"
kubectl exec web-2 -- sh -c "echo 'Hello from web-2' > /usr/share/nginx/html/index.html"

# 验证数据独立
kubectl exec web-0 -- cat /usr/share/nginx/html/index.html
kubectl exec web-1 -- cat /usr/share/nginx/html/index.html
kubectl exec web-2 -- cat /usr/share/nginx/html/index.html
```

**预期输出:**
```
Hello from web-0
Hello from web-1
Hello from web-2
```

**验证Pod重建后数据持久:**

```bash
# 删除web-1
kubectl delete pod web-1

# 等待重建
kubectl wait --for=condition=Ready pod/web-1 --timeout=120s
echo "web-1 已重建"

# 验证数据仍然存在
kubectl exec web-1 -- cat /usr/share/nginx/html/index.html
```

**预期输出:**
```
Hello from web-1   ← 数据持久！
```

**验证PVC绑定关系:**

```bash
# 查看PVC详情
kubectl get pvc
kubectl describe pvc www-web-1
```

**验证点:** ✅ 每个Pod拥有独立PVC，数据持久化，重建后绑定同一PVC

**💡 知识点:**
- `volumeClaimTemplates` 为每个Pod创建独立PVC
- PVC与Pod名称对应：`www-web-0`, `www-web-1`...
- Pod删除重建后，绑定同名PVC
- 数据完全独立，互不影响
- 类比：每个数据库实例有自己的数据目录

---

### Step 6: 观察有序扩容和缩容

**有序扩容:**

```bash
# 扩容到5个副本
kubectl scale statefulset web --replicas=5

# 观察有序创建（web-3 → web-4）
kubectl get pod -l app=nginx -w
```

**预期输出:**
```
web-0   1/1   Running   0
web-1   1/1   Running   0
web-2   1/1   Running   0
web-3   0/1   Pending   0       ← 先创建web-3
web-3   1/1   Running   0       ← web-3就绪后创建web-4
web-4   0/1   Pending   0
web-4   1/1   Running   0
```

按 `Ctrl+C` 退出watch。

**有序缩容:**

```bash
# 缩容到2个副本
kubectl scale statefulset web --replicas=2

# 观察有序删除（web-4 → web-3 → web-2）
kubectl get pod -l app=nginx -w
```

**预期输出:**
```
web-4   1/1   Terminating   0   ← 先删除最大序号
web-3   1/1   Terminating   0   ← 再删除web-3
web-2   1/1   Terminating   0   ← 再删除web-2
```

按 `Ctrl+C` 退出watch。

**验证PVC保留（即使Pod被删除）:**

```bash
# 查看PVC（web-2/3/4的PVC仍然存在！）
kubectl get pvc
```

**预期输出:**
```
NAME        STATUS   CAPACITY
www-web-0   Bound    1Gi      ← 当前Pod的PVC
www-web-1   Bound    1Gi      ← 当前Pod的PVC
www-web-2   Bound    1Gi      ← 缩容后PVC仍保留
www-web-3   Bound    1Gi      ← 缩容后PVC仍保留
www-web-4   Bound    1Gi      ← 缩容后PVC仍保留
```

**验证点:** ✅ 扩容从小到大，缩容从大到小，PVC不会自动删除

**💡 知识点:**
- 扩容：从当前最大序号开始，依次创建
- 缩容：从当前最大序号开始，依次删除
- PVC不会随Pod删除而删除（保护数据）
- 重新扩容时，会重用已有PVC
- 需要手动删除不再需要的PVC

---

### Step 7: 滚动更新策略

```bash
# 恢复到3个副本
kubectl scale statefulset web --replicas=3
kubectl wait --for=condition=Ready pod -l app=nginx --timeout=120s

# 查看当前镜像版本
kubectl get statefulset web -o jsonpath='{.spec.template.spec.containers[0].image}'
echo ""

# 更新镜像（模拟应用升级）
kubectl set image statefulset/web nginx=nginx:1.25

# 观察滚动更新（从最大序号开始）
kubectl rollout status statefulset/web
```

**更新观察（从web-2开始，倒序更新）:**

```bash
# 查看更新历史
kubectl rollout history statefulset/web

# 查看每个Pod的镜像版本
kubectl get pod -l app=nginx -o jsonpath='{range .items[*]}{.metadata.name}: {.spec.containers[0].image}{"\n"}{end}'
```

**预期输出:**
```
web-0: nginx:1.25
web-1: nginx:1.25
web-2: nginx:1.25
```

**分区更新（高级：只更新部分Pod）:**

```bash
# 设置partition=2，只更新ordinal>=2的Pod
kubectl patch statefulset web -p '{"spec":{"updateStrategy":{"rollingUpdate":{"partition":2}}}}'

# 更新镜像
kubectl set image statefulset/web nginx=nginx:1.26

# 检查：只有web-2更新了
kubectl get pod -l app=nginx -o jsonpath='{range .items[*]}{.metadata.name}: {.spec.containers[0].image}{"\n"}{end}'
```

**预期输出:**
```
web-0: nginx:1.25   ← 未更新（ordinal < partition）
web-1: nginx:1.25   ← 未更新
web-2: nginx:1.26   ← 已更新（ordinal >= partition）
```

**恢复全量更新:**

```bash
kubectl patch statefulset web -p '{"spec":{"updateStrategy":{"rollingUpdate":{"partition":0}}}}'
kubectl rollout status statefulset/web
```

**验证点:** ✅ 滚动更新从最大序号开始，分区更新可精细控制

**💡 知识点:**
- 默认策略：RollingUpdate（从最大序号开始）
- 分区更新（partition）：只更新 ordinal >= partition 的Pod
- 适用场景：金丝雀发布、灰度测试
- OnDelete策略：手动删除Pod才会更新
- 回滚：`kubectl rollout undo statefulset/web`

---

## ✅ 验证清单

- [ ] 理解StatefulSet与Deployment的区别
- [ ] 掌握Headless Service的配置（clusterIP: None）
- [ ] 验证Pod的稳定网络标识（DNS）
- [ ] 理解每个Pod独立的PVC
- [ ] 观察有序部署过程（0→1→2）
- [ ] 验证数据持久化（Pod重建后数据保留）
- [ ] 观察有序扩缩容机制
- [ ] 理解滚动更新策略和分区更新

---

## 🔧 故障排查

### 问题1: Pod一直Pending

**原因:** PVC无法创建或绑定

**排查:**
```bash
# 检查PVC状态
kubectl get pvc

# 检查StorageClass
kubectl get storageclass

# 查看Pod事件
kubectl describe pod web-0

# 查看PVC事件
kubectl describe pvc www-web-0
```

**常见原因:**
- StorageClass不存在：确认 `local-path` StorageClass存在
- 存储空间不足：检查节点磁盘空间

---

### 问题2: Pod创建卡住（后续Pod不创建）

**原因:** StatefulSet等待前一个Pod Ready

**排查:**
```bash
# 检查卡住的Pod
kubectl describe pod web-0

# 查看日志
kubectl logs web-0

# 检查就绪探针
kubectl get pod web-0 -o yaml | grep -A 10 readiness
```

**说明:** 这是StatefulSet的正常行为，等待前一个Pod Ready才创建下一个。

---

### 问题3: DNS解析失败

**原因:** Headless Service未创建或selector不匹配

**排查:**
```bash
# 确认Service存在
kubectl get svc nginx

# 确认selector匹配
kubectl get svc nginx -o yaml | grep -A 5 selector

# 确认Pod标签
kubectl get pod -l app=nginx --show-labels

# 测试DNS
kubectl run dns-debug --image=busybox:1.28 --rm -it --restart=Never -- nslookup nginx.default.svc.cluster.local
```

---

### 问题4: 缩容后PVC残留

**原因:** StatefulSet设计行为，PVC不自动删除

**说明:** 这是保护数据的设计，需手动清理：
```bash
# 手动删除不需要的PVC
kubectl delete pvc www-web-2 www-web-3 www-web-4
```

---

## 🧪 扩展练习

### 1. OnDelete更新策略

手动控制更新时机：

```yaml
spec:
  updateStrategy:
    type: OnDelete   # 删除Pod时才会使用新版本重建
```

### 2. Pod管理策略

并行创建（不推荐用于真正有状态应用）：

```yaml
spec:
  podManagementPolicy: Parallel
  # 同时启动所有Pod，不保证顺序
```

### 3. 模拟MySQL主从

```yaml
# 主节点：mysql-0（固定DNS）
# 从节点：mysql-1, mysql-2
# 从节点通过 mysql-0.mysql.default.svc.cluster.local 连接主节点
```

---

## 📖 知识总结

### StatefulSet vs Deployment 对比

| 特性 | Deployment | StatefulSet |
|------|-----------|------------|
| Pod名称 | 随机（deploy-xxx-yyy） | 固定（web-0, web-1） |
| 网络标识 | 不稳定 | 稳定DNS |
| 存储 | 共享或无状态 | 每个Pod独立PVC |
| 启动顺序 | 并行 | 有序（0→1→2） |
| 扩容顺序 | 并行 | 有序（从小到大） |
| 缩容顺序 | 任意 | 有序（从大到小） |
| 更新顺序 | 任意 | 有序（从大到小） |
| 适用场景 | 无状态应用 | 有状态应用 |

### StatefulSet三大保证

**1. 稳定的网络标识**
```
格式：<pod-name>.<service-name>.<namespace>.svc.cluster.local
示例：web-0.nginx.default.svc.cluster.local
特性：Pod重建后DNS名称不变
```

**2. 稳定的持久化存储**
```
PVC命名：<template-name>-<pod-name>
示例：www-web-0
特性：Pod重建后绑定同一PVC，数据不丢失
```

**3. 有序的部署和扩展**
```
创建：0 → 1 → 2（前一个Ready才创建下一个）
删除：2 → 1 → 0（从最大序号开始）
更新：2 → 1 → 0（从最大序号开始）
```

### 实际应用场景

**数据库:**
- MySQL主从（主节点固定标识）
- PostgreSQL高可用
- MongoDB副本集
- 每个实例需要独立数据目录

**消息队列:**
- Kafka（每个Broker有ID）
- RabbitMQ集群
- 有状态的消息存储

**分布式协调:**
- ZooKeeper（需要固定成员标识）
- etcd集群
- Consul
- 集群成员需要互相发现

### 最佳实践

1. **始终配合Headless Service**
   - StatefulSet必需
   - 提供稳定DNS

2. **使用volumeClaimTemplates**
   - 自动创建PVC
   - 独立存储

3. **理解PVC生命周期**
   - 缩容不自动删除PVC
   - 手动清理不需要的PVC
   - 扩容会重用已有PVC

4. **监控有序部署**
   - 关注Pod启动顺序
   - 确保前置Pod Ready

5. **数据备份**
   - PVC不自动备份
   - 生产环境需配置备份策略

---

## 🧹 清理环境

```bash
# 删除StatefulSet（不会删除PVC）
kubectl delete statefulset web

# 删除Service
kubectl delete svc nginx

# 查看残留的PVC
kubectl get pvc

# 手动删除PVC（StatefulSet不会自动删除）
kubectl delete pvc -l app=nginx

# 删除配置文件
rm -f headless-service.yaml statefulset.yaml

# 验证清理完成
kubectl get statefulset,svc,pvc,pod -l app=nginx
```

**注意:** StatefulSet删除后PVC仍然保留，这是保护数据的设计。生产环境中，清理前请确认数据已备份。

---

## 📎 参考资料

- [StatefulSet官方文档](https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/)
- [StatefulSet基础教程](https://kubernetes.io/docs/tutorials/stateful-application/basic-stateful-set/)
- [Headless Service文档](https://kubernetes.io/docs/concepts/services-networking/service/#headless-services)

---

**实验9完成！** 🎉

继续下一个实验前，确保理解：
- StatefulSet的三大特性（网络、存储、顺序）
- 与Deployment的本质区别
- Headless Service的作用
- 有序部署和扩缩容机制
- 实际应用场景（数据库、消息队列、分布式协调）
