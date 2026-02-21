# 实验6: DNS服务发现

## 📋 实验信息

- **难度**: ⭐⭐⭐ (中级)
- **时长**: 35-40分钟
- **环境**: K3s单节点集群（CoreDNS）
- **前置**: 完成实验3，理解Service概念

## 🎯 学习目标

通过本实验，你将：
1. 理解Kubernetes DNS服务的工作原理
2. 掌握Service DNS记录格式和解析
3. 学习Pod DNS记录的配置和使用
4. 理解跨命名空间的DNS访问方法
5. 掌握Headless Service的DNS特性
6. 学习常用的DNS调试技巧

## 📚 前置知识

- 完成实验3，理解Service概念
- 了解DNS基础知识
- 理解FQDN（全限定域名）概念
- 了解nslookup基本使用

---

## 🐳 实验镜像说明

本实验使用的镜像：

### busybox:1.28
- **用途**: DNS查询和测试
- **工具**: nslookup, ping, wget
- **场景**: 所有DNS测试步骤

### nginx
- **用途**: 创建测试Service
- **场景**: 提供DNS解析目标

**💡 DNS实验特点:**
- 主要使用nslookup进行DNS查询
- 验证不同DNS记录类型
- 理解DNS在服务发现中的作用
- 这是微服务架构的基础

**📖 关于CoreDNS:**
- Kubernetes默认DNS服务器
- 自动为Service创建DNS记录
- 支持自定义DNS配置
- 高性能、轻量级

---

## ⚠️ 开始实验前

VM刚启动时，K3s需要约2-3分钟完成初始化。请先确认环境就绪：

```bash
# 等待节点Ready
kubectl wait --for=condition=Ready node --all --timeout=180s

# 确认系统Pod运行正常
kubectl get pod -n kube-system
```

如果看到节点NotReady或大量Pod处于Pending，请等待2-3分钟再继续。

---

## 🚀 实验步骤

### Step 1: 验证CoreDNS服务

首先检查CoreDNS服务状态：

```bash
# 查看CoreDNS Pod
kubectl get pod -n kube-system -l k8s-app=kube-dns

# 查看CoreDNS Service
kubectl get svc -n kube-system kube-dns

# 查看CoreDNS配置
kubectl get configmap coredns -n kube-system -o yaml | grep -A 10 "Corefile:"
```

**预期输出:**
```
NAME                      READY   STATUS    RESTARTS
coredns-xxx               1/1     Running   0

NAME       TYPE        CLUSTER-IP   PORT(S)
kube-dns   ClusterIP   10.43.0.10   53/UDP,53/TCP
```

**验证点:** ✅ CoreDNS运行正常，监听53端口

**💡 知识点:** CoreDNS是Kubernetes的DNS服务器，Service名称是kube-dns（历史原因），ClusterIP通常是10.43.0.10（K3s）

---

### Step 2: 创建测试环境

创建测试Service和Pod：

```bash
# 创建nginx Deployment和Service
kubectl create deployment web --image=nginx --replicas=2
kubectl expose deployment web --port=80 --name=web-service

# 创建DNS测试Pod
kubectl run dns-test --image=busybox:1.28 --command -- sleep 3600

# 等待资源就绪
kubectl wait --for=condition=Ready pod -l app=web --timeout=60s
kubectl wait --for=condition=Ready pod dns-test --timeout=60s

# 查看资源
kubectl get pod,svc
```

**预期输出:** web Pod和dns-test Pod都处于Running状态，web-service创建成功

**验证点:** ✅ Service和测试Pod创建成功

**💡 知识点:** busybox:1.28包含完整的DNS工具，Service会自动创建DNS记录

---

### Step 3: Service DNS - 短名称解析

在同一命名空间内使用短名称：

```bash
# 使用短名称解析Service
kubectl exec dns-test -- nslookup web-service

# 使用wget测试（验证DNS工作）
kubectl exec dns-test -- wget -qO- http://web-service --timeout=2
```

**预期输出:** DNS解析到Service ClusterIP (10.43.x.x)

**验证点:** ✅ 短名称解析到Service ClusterIP

**💡 知识点:** 同一命名空间内可以使用短名称，DNS自动补全为FQDN

---

### Step 4: Service DNS - FQDN解析

使用完整域名（FQDN）：

```bash
# 使用完整的FQDN
kubectl exec dns-test -- nslookup web-service.default.svc.cluster.local

# 使用简化形式
kubectl exec dns-test -- nslookup web-service.default
```

**预期输出:** 所有查询都解析到相同的IP

**验证点:** ✅ FQDN和简化形式都能解析

**💡 知识点:** FQDN格式是`<service>.<namespace>.svc.cluster.local`，可以省略后缀

---

### Step 5: 跨命名空间DNS访问

测试跨命名空间的DNS解析：

```bash
# 创建新命名空间和Service
kubectl create namespace test-ns
kubectl create deployment app -n test-ns --image=nginx
kubectl expose deployment app -n test-ns --port=80 --name=app-service
kubectl wait --for=condition=Ready pod -l app=app -n test-ns --timeout=60s

# 从default命名空间访问test-ns的Service
kubectl exec dns-test -- nslookup app-service.test-ns.svc.cluster.local

# 使用wget测试
kubectl exec dns-test -- wget -qO- http://app-service.test-ns.svc.cluster.local --timeout=2
```

**预期输出:** 成功解析并访问test-ns中的Service

**验证点:** ✅ 跨命名空间DNS解析成功

**💡 知识点:** 跨命名空间必须使用完整名称，至少包含`<service>.<namespace>`，这是多环境/多项目隔离的基础

---

### Step 6: Headless Service DNS

探索Headless Service的DNS特性：

```bash
# 创建Headless Service（ClusterIP: None）
cat > headless-service.yaml <<EOF
apiVersion: v1
kind: Service
metadata:
  name: headless-service
spec:
  clusterIP: None
  selector:
    app: web
  ports:
  - port: 80
EOF

kubectl apply -f headless-service.yaml

# 解析Headless Service（返回所有Pod IP）
kubectl exec dns-test -- nslookup headless-service
```

**预期输出:** 返回多个Address（所有Pod IP）

**验证点:** ✅ Headless Service返回所有Pod IP

**💡 知识点:** Headless Service没有ClusterIP，DNS直接返回Pod IP列表

---

### Step 7: DNS调试

查看DNS配置和调试：

```bash
# 检查Pod的DNS配置
kubectl exec dns-test -- cat /etc/resolv.conf

# 测试DNS服务器连通性
kubectl exec dns-test -- nslookup kubernetes.default

# 查看CoreDNS日志（如有问题）
kubectl logs -n kube-system -l k8s-app=kube-dns --tail=10
```

**预期输出:** nameserver 10.43.0.10, search域列表, options ndots:5

**验证点:** ✅ DNS配置正确

**💡 知识点:** nameserver指向CoreDNS，search用于自动补全，ndots影响查询行为

---

## ✅ 验证清单

- [ ] CoreDNS服务运行正常
- [ ] Service短名称解析成功
- [ ] Service FQDN解析成功
- [ ] 理解FQDN的格式和简化形式
- [ ] 跨命名空间DNS访问成功
- [ ] Headless Service返回Pod IP列表
- [ ] 理解Pod的DNS配置

---

## 🔧 故障排查

### 问题1: DNS解析失败

**原因:** CoreDNS服务异常

**解决:** 检查CoreDNS状态并重启
```bash
kubectl get pod -n kube-system -l k8s-app=kube-dns
kubectl logs -n kube-system -l k8s-app=kube-dns
kubectl rollout restart deployment coredns -n kube-system
```

---

### 问题2: 跨命名空间访问失败

**原因:** 域名不完整

**解决:** 必须使用至少`<service>.<namespace>`格式，同命名空间才能用短名称

---

### 问题3: Headless Service解析异常

**原因:** Pod选择器不匹配

**解决:** 检查Service选择器和Pod标签是否匹配
```bash
kubectl get svc headless-service -o yaml | grep -A 3 selector
kubectl get pod --show-labels
```

---

## 🧪 扩展练习

### 1. 自定义Pod DNS记录

为Pod配置hostname和subdomain创建可预测的DNS名称：

```yaml
spec:
  hostname: my-pod
  subdomain: web-service
```

DNS记录: `my-pod.web-service.default.svc.cluster.local`

---

### 2. DNS配置优化

调整ndots减少DNS查询次数：

```yaml
dnsConfig:
  options:
  - name: ndots
    value: "1"
```

---

## 📖 知识总结

### DNS记录类型

**1. Service DNS（标准）**
- 格式: `<service>.<namespace>.svc.cluster.local`
- 解析: Service ClusterIP

**2. Headless Service DNS**
- 格式: `<service>.<namespace>.svc.cluster.local`
- 解析: 所有Pod IP列表

**3. Pod DNS（需配置hostname/subdomain）**
- 格式: `<pod-ip>.<namespace>.pod.cluster.local`
- 解析: Pod IP

### DNS查询流程

Pod发起查询 → CoreDNS (10.43.0.10) → Kubernetes API → 返回IP → 建立连接

### 域名简化规则

**同命名空间:** `web-service` 或 `web-service.default.svc.cluster.local` 都可以

**跨命名空间:** 至少需要 `app-service.test-ns`，建议使用FQDN

### 最佳实践

1. **使用Service名称而非IP** - 便于维护，自动负载均衡
2. **跨命名空间使用FQDN** - 避免歧义
3. **Headless Service用于有状态应用** - 直接访问Pod
4. **合理配置ndots** - 影响DNS查询性能

---

## 🧹 清理环境

```bash
# 删除Service
kubectl delete svc web-service headless-service

# 删除test-ns中的资源
kubectl delete svc app-service -n test-ns
kubectl delete deployment app -n test-ns

# 删除Deployment和Pod
kubectl delete deployment web
kubectl delete pod dns-test

# 删除命名空间
kubectl delete namespace test-ns

# 删除配置文件
rm -f headless-service.yaml

# 验证清理
kubectl get all
```

---

## 📚 参考资料

- [Kubernetes DNS官方文档](https://kubernetes.io/docs/concepts/services-networking/dns-pod-service/)
- [CoreDNS文档](https://coredns.io/manual/toc/)
- [DNS调试指南](https://kubernetes.io/docs/tasks/administer-cluster/dns-debugging-resolution/)

---

**实验6完成！** 🎉

继续下一个实验前，确保理解：
- Service DNS记录的格式和使用
- 跨命名空间DNS访问方法
- Headless Service的特殊性
- DNS调试的基本技巧
- DNS在微服务架构中的重要作用

祝你学习愉快！🚀
