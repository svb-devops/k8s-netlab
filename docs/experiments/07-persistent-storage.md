# 实验7: 持久化存储 (PV/PVC/StorageClass)

## 📋 实验信息

- **难度**: ⭐⭐⭐ (中级)
- **时长**: 40-45分钟
- **环境**: K3s单节点集群（local-path-provisioner）
- **前置**: 完成实验1-3，理解Pod和Deployment

## 🎯 学习目标

通过本实验，你将：
1. 理解Kubernetes存储模型和三层抽象
2. 掌握PersistentVolume (PV) 的作用和生命周期
3. 学习PersistentVolumeClaim (PVC) 的声明和使用
4. 理解StorageClass的动态供应机制
5. 掌握K3s local-path-provisioner的使用
6. 验证数据持久化效果（Pod删除后数据保留）
7. 学习存储的生命周期管理和扩容

## 📚 前置知识

- 完成实验1-3，理解Pod基础
- 了解容器存储的临时性
- 理解Volume的基本概念
- 了解数据持久化需求

---

## 🐳 实验镜像说明

本实验使用的镜像：

### busybox:1.28
- **用途**: 数据持久化测试
- **工具**: sh, echo, cat等
- **场景**: 写入和读取测试数据

### nginx
- **用途**: Web应用持久化场景（可选）
- **场景**: 演示日志和配置持久化

**💡 存储实验特点:**
- 验证数据持久化（Pod删除后数据保留）
- 理解临时存储 vs 持久化存储
- 学习生产环境存储管理
- K3s使用local-path-provisioner

**📖 关于local-path-provisioner:**
- K3s默认存储供应商
- 使用主机本地路径
- 动态创建PV
- 适合单节点测试环境
- 生产环境建议NFS、Ceph等

---

## ⚠️ 开始实验前

### 环境就绪检查

VM刚启动时，K3s需要2-3分钟完成初始化。请先验证环境就绪：

```bash
# 等待K3s完全就绪
kubectl wait --for=condition=Ready node --all --timeout=180s

# 验证系统Pod都在运行
kubectl get pod -n kube-system

# 确认没有CrashLoopBackOff或Error状态
```

**预期结果:**
- 所有节点Ready
- 系统Pod大部分Running
- 如果部分Pod正在启动，等待它们完成

**💡 为什么需要等待:**
- VM网络初始化需要时间
- K3s系统组件启动需要时间
- 等待2-3分钟确保环境稳定
- 避免实验过程中的不必要错误

**如果看到NetworkPolicy相关警告:**
```
controller.go:xxx] Error updating node...
```
这是正常的，等待2-3分钟会自动恢复。

---

## 🚀 实验步骤

### Step 1: 演示容器存储的临时性问题

**开始前快速检查:**

```bash
# 确认环境就绪（如果刚启动VM）
kubectl get nodes
# 应该显示: Ready

kubectl get pod -n kube-system
# 大部分应该: Running
```

如果看到NotReady或很多Pending，请等待2-3分钟。

首先验证没有持久化存储时的问题：

```bash
# 创建一个Pod并写入数据
kubectl run temp-pod --image=busybox:1.28 --command -- sh -c "echo 'Important Data' > /tmp/data.txt && sleep 3600"

# 等待Pod运行
kubectl wait --for=condition=Ready pod/temp-pod --timeout=60s

# 验证数据存在
kubectl exec temp-pod -- cat /tmp/data.txt

# 删除Pod
kubectl delete pod temp-pod

# 重新创建同名Pod
kubectl run temp-pod --image=busybox:1.28 --command -- sh -c "sleep 3600"
kubectl wait --for=condition=Ready pod/temp-pod --timeout=60s

# 尝试读取数据（会失败）
kubectl exec temp-pod -- cat /tmp/data.txt 2>&1 || echo "❌ 数据丢失！"

# 清理
kubectl delete pod temp-pod
```

**预期结果:**
```
第一次: Important Data
删除并重建后: cat: can't open '/tmp/data.txt': No such file or directory
❌ 数据丢失！
```

**验证点:** ✅ 理解容器存储的临时性，数据随Pod删除而丢失

**💡 知识点:**
- 容器文件系统是临时的
- Pod删除后数据全部丢失
- 需要持久化存储来保留数据
- 这就是PV/PVC存储的原因

---

### Step 2: 查看K3s默认StorageClass

```bash
# 查看StorageClass列表
kubectl get storageclass
kubectl get sc

# 查看默认StorageClass详情
kubectl describe storageclass local-path

# 查看local-path-provisioner组件
kubectl get pod -n kube-system | grep local-path
```

**预期输出:**
```
NAME                   PROVISIONER             RECLAIMPOLICY   VOLUMEBINDINGMODE
local-path (default)   rancher.io/local-path   Delete          WaitForFirstConsumer

Name:            local-path
IsDefaultClass:  Yes
Provisioner:     rancher.io/local-path
ReclaimPolicy:   Delete
VolumeBindingMode: WaitForFirstConsumer
```

**验证点:** ✅ K3s默认提供local-path StorageClass

**💡 知识点:**
- StorageClass定义存储类型和参数
- Provisioner负责动态创建PV
- ReclaimPolicy: Delete（PVC删除时删除PV和数据）
- WaitForFirstConsumer：Pod调度后才创建PV
- `(default)` 标记表示默认StorageClass

---

### Step 3: 创建PersistentVolumeClaim

创建PVC配置文件：

```bash
cat > my-pvc.yaml <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-pvc
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
  storageClassName: local-path
EOF

# 应用PVC
kubectl apply -f my-pvc.yaml

# 查看PVC状态
kubectl get pvc

# 查看PVC详情
kubectl describe pvc my-pvc
```

**预期输出:**
```
NAME     STATUS    VOLUME   CAPACITY   ACCESS MODES   STORAGECLASS
my-pvc   Pending   -        -          -              local-path
```

**验证点:** ✅ PVC创建成功，状态为Pending（等待Pod使用）

**💡 知识点:**
- PVC是存储请求，声明需要多少存储
- accessModes: ReadWriteOnce（单节点读写）
- storage: 请求1GB存储空间
- Status: Pending是正常的（WaitForFirstConsumer）
- PV会在Pod使用PVC时自动创建

---

### Step 4: 创建Pod挂载PVC

创建Pod配置文件：

```bash
cat > pod-with-pvc.yaml <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: test-pod
spec:
  containers:
  - name: test-container
    image: busybox:1.28
    command: ["sh", "-c", "sleep 3600"]
    volumeMounts:
    - name: my-storage
      mountPath: /data
  volumes:
  - name: my-storage
    persistentVolumeClaim:
      claimName: my-pvc
EOF

# 应用Pod
kubectl apply -f pod-with-pvc.yaml

# 等待Pod运行
kubectl wait --for=condition=Ready pod/test-pod --timeout=60s

# 再次查看PVC状态（应该变为Bound）
kubectl get pvc

# 查看自动创建的PV
kubectl get pv
```

**预期输出:**
```
PVC状态:
NAME     STATUS   VOLUME                                     CAPACITY   ACCESS MODES
my-pvc   Bound    pvc-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx   1Gi        RWO

PV状态:
NAME                                       CAPACITY   ACCESS MODES   RECLAIM POLICY   STATUS
pvc-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx   1Gi        RWO            Delete           Bound
```

**验证点:** ✅ PVC绑定到自动创建的PV，Pod成功挂载

**💡 知识点:**
- volumeMounts: 容器内挂载点（/data）
- volumes: 引用PVC名称
- Pod创建后，PVC从Pending变为Bound
- StorageClass自动创建PV
- PV与PVC一一绑定

---

### Step 5: 验证数据写入持久化存储

```bash
# 在Pod中写入数据
kubectl exec test-pod -- sh -c "echo 'Persistent Data - $(date)' > /data/important.txt"
kubectl exec test-pod -- sh -c "echo 'Line 1' >> /data/important.txt"
kubectl exec test-pod -- sh -c "echo 'Line 2' >> /data/important.txt"

# 读取数据
kubectl exec test-pod -- cat /data/important.txt

# 查看挂载点磁盘使用
kubectl exec test-pod -- df -h /data

# 查看主机上的实际存储位置
kubectl get pv -o jsonpath='{.items[0].spec.hostPath.path}' 2>/dev/null || \
  kubectl get pv -o yaml | grep "path:"
```

**预期输出:**
```
Persistent Data - Tue Feb 19 10:30:15 UTC 2026
Line 1
Line 2

Filesystem      Size  Used Avail Use% Mounted on
/dev/sda        ...   ...  ...   ...  /data
```

**验证点:** ✅ 数据成功写入持久化存储

**💡 知识点:**
- 数据写入挂载的 /data 目录
- 实际存储在主机的 local-path 目录
- 数据独立于Pod的生命周期
- 此时数据已安全持久化

---

### Step 6: 删除Pod验证数据保留

```bash
# 删除Pod
kubectl delete pod test-pod

# 验证PVC和PV仍然存在
kubectl get pvc
kubectl get pv

# 重新创建Pod（使用相同的PVC）
kubectl apply -f pod-with-pvc.yaml

# 等待Pod运行
kubectl wait --for=condition=Ready pod/test-pod --timeout=60s

# 读取之前写入的数据
kubectl exec test-pod -- cat /data/important.txt
```

**预期输出:**
```
PVC仍然存在:
NAME     STATUS   VOLUME                                     CAPACITY
my-pvc   Bound    pvc-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx   1Gi

读取数据:
Persistent Data - Tue Feb 19 10:30:15 UTC 2026
Line 1
Line 2
```

**验证点:** ✅ Pod删除后数据保留，新Pod可以访问相同数据

**💡 知识点:**
- PV的生命周期独立于Pod
- Pod删除不影响PVC和PV
- 新Pod挂载同一PVC可访问相同数据
- 这就是持久化存储的核心价值
- 适用场景：数据库、日志、用户上传文件

---

### Step 7: Deployment使用PVC（实际场景）

创建Deployment配置，演示生产场景：

```bash
cat > deployment-with-pvc.yaml <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: nginx-pvc
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 500Mi
  storageClassName: local-path
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-with-storage
spec:
  replicas: 1
  selector:
    matchLabels:
      app: nginx-storage
  template:
    metadata:
      labels:
        app: nginx-storage
    spec:
      containers:
      - name: nginx
        image: nginx
        volumeMounts:
        - name: nginx-data
          mountPath: /usr/share/nginx/html
      volumes:
      - name: nginx-data
        persistentVolumeClaim:
          claimName: nginx-pvc
EOF

# 应用配置
kubectl apply -f deployment-with-pvc.yaml

# 等待Pod运行
kubectl wait --for=condition=Ready pod -l app=nginx-storage --timeout=60s

# 写入自定义页面
kubectl exec deployment/nginx-with-storage -- sh -c \
  "echo '<h1>Persistent Web Page</h1>' > /usr/share/nginx/html/index.html"

# 获取Pod名称
POD_NAME=$(kubectl get pod -l app=nginx-storage -o jsonpath='{.items[0].metadata.name}')

# 验证内容
kubectl exec $POD_NAME -- cat /usr/share/nginx/html/index.html

# 删除Pod（Deployment会自动重建）
kubectl delete pod $POD_NAME

# 等待新Pod启动
kubectl wait --for=condition=Ready pod -l app=nginx-storage --timeout=60s

# 验证数据仍然存在
kubectl exec deployment/nginx-with-storage -- cat /usr/share/nginx/html/index.html
```

**预期输出:**
```
两次都显示: <h1>Persistent Web Page</h1>
```

**验证点:** ✅ Deployment中使用PVC实现数据持久化

**💡 知识点:**
- Deployment可以使用PVC
- Pod重建后数据保持
- 实际应用场景：Web服务、数据库等
- 单个PVC只能被一个Pod挂载（RWO模式）
- 多副本场景需使用StatefulSet+多PVC

---

### Step 8: 查看存储使用情况

```bash
# 查看所有PVC
kubectl get pvc

# 查看所有PV
kubectl get pv

# 查看PVC使用的存储大小
kubectl exec test-pod -- df -h /data

# 查看主机存储位置
sudo ls -lh /var/lib/rancher/k3s/storage/ 2>/dev/null || \
  echo "提示: 需要在节点上执行以查看实际存储"

# 查看PV详细信息
PV_NAME=$(kubectl get pvc my-pvc -o jsonpath='{.spec.volumeName}')
kubectl describe pv $PV_NAME
```

**💡 知识点:**
- PV实际存储在主机文件系统
- local-path默认路径：/var/lib/rancher/k3s/storage/
- 每个PV有独立的目录
- 生产环境需监控存储使用量

---

## ✅ 验证清单

实验完成后，确认以下要点：

- [ ] 理解容器存储的临时性问题
- [ ] 了解K3s默认StorageClass
- [ ] 成功创建PVC
- [ ] PVC绑定到自动创建的PV
- [ ] Pod成功挂载PVC
- [ ] 数据写入持久化存储
- [ ] Pod删除后数据保留
- [ ] 新Pod可以访问相同数据
- [ ] 理解PV、PVC、StorageClass三者关系

---

## 🔧 故障排查

### 问题1: PVC一直处于Pending状态

**原因:** WaitForFirstConsumer模式，等待Pod使用

**解决:**
- 这是正常行为
- 创建使用该PVC的Pod后会自动Bound
- 或检查StorageClass配置

**验证:**
```bash
kubectl describe pvc <pvc-name>
# 查看Events部分
```

---

### 问题2: Pod无法启动，挂载失败

**原因:** PVC不存在或状态异常

**解决:**
```bash
# 检查PVC状态
kubectl get pvc

# 检查Pod Events
kubectl describe pod <pod-name>

# 检查PV状态
kubectl get pv
```

---

### 问题3: 数据没有持久化

**原因:** 挂载路径错误或未使用PVC

**解决:**
```bash
# 检查Pod的Volume配置
kubectl get pod <pod-name> -o yaml | grep -A 10 volumes

# 验证挂载点
kubectl exec <pod-name> -- df -h

# 确认写入正确路径
kubectl exec <pod-name> -- ls -la /data
```

---

### 问题4: VM启动时K3s不稳定

**现象:**
- Pod启动失败
- NetworkPolicy相关错误日志
- 节点NotReady

**原因:** VM网络初始化未完成

**解决:**
```bash
# 等待节点就绪
kubectl wait --for=condition=Ready node --all --timeout=180s

# 检查系统Pod状态
kubectl get pod -n kube-system

# 等待2-3分钟后重试
```

**预防措施:**
- VM启动后等待2-3分钟再开始实验
- 先运行环境就绪检查
- 确认节点Ready和系统Pod运行后再继续

---

### 问题5: 存储空间不足

**原因:** 请求的存储超过可用空间

**解决:**
```bash
# 查看主机存储空间
df -h /var/lib/rancher/k3s/storage/

# 调整PVC请求大小
# 编辑PVC: kubectl edit pvc <pvc-name>
# 或删除重建
```

---

## 🧪 扩展练习

### 1. 多PVC场景

创建应用使用多个PVC：

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: multi-pvc-pod
spec:
  containers:
  - name: app
    image: busybox:1.28
    command: ["sleep", "3600"]
    volumeMounts:
    - name: data-volume
      mountPath: /data
    - name: logs-volume
      mountPath: /logs
  volumes:
  - name: data-volume
    persistentVolumeClaim:
      claimName: data-pvc
  - name: logs-volume
    persistentVolumeClaim:
      claimName: logs-pvc
```

### 2. 不同访问模式对比

```bash
# ReadWriteOnce - 单节点读写（最常用）
accessModes:
  - ReadWriteOnce

# ReadOnlyMany - 多节点只读
accessModes:
  - ReadOnlyMany
```

### 3. 手动创建PV（静态供应）

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: manual-pv
spec:
  capacity:
    storage: 2Gi
  accessModes:
    - ReadWriteOnce
  hostPath:
    path: /tmp/manual-pv-data
```

---

## 📖 知识总结

### Kubernetes存储三层抽象

```
1. StorageClass（存储类）
   - 定义存储类型和参数
   - 指定Provisioner
   - 设置回收策略

2. PersistentVolume（持久卷）
   - 集群级别的存储资源
   - 独立于Pod的生命周期
   - 由管理员创建或动态供应

3. PersistentVolumeClaim（持久卷声明）
   - 用户的存储请求
   - 绑定到PV
   - Pod通过PVC使用存储
```

### 关键概念

**AccessModes（访问模式）:**
- ReadWriteOnce (RWO): 单节点读写
- ReadOnlyMany (ROX): 多节点只读
- ReadWriteMany (RWX): 多节点读写

**ReclaimPolicy（回收策略）:**
- Delete: PVC删除时删除PV和数据
- Retain: 保留PV和数据，需手动清理
- Recycle: 清除数据后重用（已弃用）

**VolumeBindingMode:**
- Immediate: 立即绑定
- WaitForFirstConsumer: 等待Pod调度

### 工作流程

```
1. 创建PVC（用户请求存储）
2. StorageClass的Provisioner创建PV
3. PVC绑定到PV
4. Pod引用PVC
5. 容器挂载Volume
6. 应用读写数据
7. Pod删除，PVC和PV保持
8. 新Pod可以重用PVC
```

### 最佳实践

1. **使用StorageClass动态供应**
   - 避免手动创建PV
   - 自动化管理
   - 更灵活

2. **合理设置存储大小**
   - 根据实际需求
   - 考虑增长空间
   - 避免浪费

3. **了解回收策略**
   - 需要数据用Retain
   - 临时数据用Delete
   - 备份重要数据

4. **选择合适的访问模式**
   - 单节点应用用RWO
   - 共享数据用RWX
   - 只读数据用ROX

5. **监控存储使用**
   - 定期检查空间
   - 清理不用的PVC
   - 防止空间耗尽

### 实际应用场景

- **数据库**: MySQL、PostgreSQL等持久化数据
- **日志存储**: 应用日志持久化
- **配置文件**: 持久化配置
- **用户上传**: 文件存储
- **缓存**: Redis等需要持久化的缓存

---

## 🧹 清理环境

```bash
# 删除Deployment
kubectl delete deployment nginx-with-storage

# 删除Pod
kubectl delete pod test-pod

# 删除PVC（会触发PV删除，ReclaimPolicy: Delete）
kubectl delete pvc my-pvc nginx-pvc

# 验证PV也被删除
kubectl get pv

# 删除配置文件
rm -f my-pvc.yaml pod-with-pvc.yaml deployment-with-pvc.yaml

# 验证清理完成
kubectl get pvc,pv,pod
```

**注意:**
- PVC删除后，由于ReclaimPolicy是Delete，PV和实际数据都会被删除
- 如果需要保留数据，应该使用Retain策略
- 生产环境删除PVC前务必确认数据已备份

---

## 📎 参考资料

- [Kubernetes存储官方文档](https://kubernetes.io/docs/concepts/storage/persistent-volumes/)
- [K3s存储文档](https://docs.k3s.io/storage)
- [local-path-provisioner](https://github.com/rancher/local-path-provisioner)

---

**实验7完成！** 🎉

继续下一个实验前，确保理解：
- PV、PVC、StorageClass三者关系
- 数据持久化的工作原理
- Pod删除后数据如何保留
- local-path-provisioner的使用
