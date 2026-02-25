# 实验5: NetworkPolicy网络策略

## 📋 实验信息

- **难度**: ⭐⭐⭐ (中级)
- **时长**: 40分钟
- **环境**: K3s单节点集群
- **前置**: 完成实验1-3，理解Pod网络和Service

## 🎯 学习目标

通过本实验，你将：
1. 理解NetworkPolicy的工作原理和应用场景
2. 掌握Pod级别的网络隔离方法
3. 学习配置Ingress规则（入站流量控制）
4. 学习配置Egress规则（出站流量控制）
5. 理解基于标签选择器的流量控制
6. 掌握网络安全的最佳实践

## 📚 前置知识

- 完成实验1-3，理解Pod网络模型
- 了解Kubernetes标签和选择器
- 理解网络安全基础概念
- 了解白名单和黑名单的区别

---

## 🐳 实验镜像说明

本实验使用的镜像：

### nginx
- **用途**: 模拟前端和后端应用
- **场景**: 创建多个Pod测试网络策略

### busybox:1.28
- **用途**: 网络连通性测试，验证NetworkPolicy规则效果

**💡 NetworkPolicy实验特点:**
- 通过网络隔离保护敏感服务
- 基于标签选择器精确控制流量
- 默认拒绝（白名单）模式，这是零信任网络的基础

**✅ CNI支持说明:** K3s默认使用Flannel CNI，完全支持NetworkPolicy功能。所有Ingress和Egress规则都能正常工作。生产环境中，Calico和Cilium提供更高级的网络策略功能（如DNS策略、L7策略等）。

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

### Step 1: 创建测试环境

创建测试命名空间和多个Pod：

```bash
# 创建测试命名空间和三个Pod（前端、后端、数据库）
kubectl create namespace netpol-test
kubectl run frontend --image=nginx --labels=app=frontend,tier=frontend -n netpol-test
kubectl run backend --image=nginx --labels=app=backend,tier=backend -n netpol-test
kubectl run database --image=nginx --labels=app=database,tier=database -n netpol-test

# 等待Pod运行并查看
kubectl wait --for=condition=Ready pod --all -n netpol-test --timeout=60s
kubectl get pod -n netpol-test --show-labels -o wide
```

**预期输出:** 三个Pod都处于Running状态，每个都有明确的app和tier标签

**验证点:** ✅ 三个Pod创建成功

**💡 知识点:** NetworkPolicy基于标签选择器工作，标签是网络策略的关键

---

### Step 2: 验证默认网络行为

测试默认状态下的网络连通性：

```bash
# 获取database IP并创建攻击者Pod
DB_IP=$(kubectl get pod database -n netpol-test -o jsonpath='{.status.podIP}')
kubectl run attacker --image=busybox:1.28 -n netpol-test --command -- sleep 3600
kubectl wait --for=condition=Ready pod attacker -n netpol-test --timeout=30s

# 测试所有Pod到database的连接
# 注意: frontend/backend使用nginx镜像（有curl无wget），attacker使用busybox（有wget）
kubectl exec frontend -n netpol-test -- curl -s --max-time 2 http://$DB_IP
kubectl exec backend -n netpol-test -- curl -s --max-time 2 http://$DB_IP
kubectl exec attacker -n netpol-test -- wget -qO- --timeout=2 http://$DB_IP
```

**预期:** 所有连接都成功 ✓（包括attacker，不安全！）

**验证点:** ✅ 默认状态下所有Pod可以互相访问

**💡 知识点:** Kubernetes默认网络是"全通"模式，NetworkPolicy用于实现"最小权限原则"

---

### Step 3: 拒绝所有入站流量

创建NetworkPolicy拒绝所有到database的流量：

```bash
cat > deny-all-to-database.yaml <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-all-to-database
  namespace: netpol-test
spec:
  podSelector:
    matchLabels:
      app: database
  policyTypes:
  - Ingress
EOF

# 应用NetworkPolicy
kubectl apply -f deny-all-to-database.yaml

# 查看NetworkPolicy
kubectl get networkpolicy -n netpol-test
kubectl describe networkpolicy deny-all-to-database -n netpol-test
```

**测试效果:**

```bash
# 测试所有连接（应该都失败）
kubectl exec frontend -n netpol-test -- curl -s --max-time 2 http://$DB_IP || echo "❌ BLOCKED"
kubectl exec backend -n netpol-test -- curl -s --max-time 2 http://$DB_IP || echo "❌ BLOCKED"
kubectl exec attacker -n netpol-test -- wget -qO- --timeout=2 http://$DB_IP || echo "❌ BLOCKED"
```

**预期:** 所有连接都被阻止 ✓

**验证点:** ✅ NetworkPolicy生效，database完全隔离

**💡 知识点:**
- `podSelector` 选择要保护的Pod
- `policyTypes: [Ingress]` 控制入站流量
- 空的Ingress规则 = 拒绝所有入站
- 这是"默认拒绝"策略

---

### Step 4: 允许特定Pod访问

创建NetworkPolicy允许backend访问database：

```bash
cat > allow-backend-to-database.yaml <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-backend-to-database
  namespace: netpol-test
spec:
  podSelector:
    matchLabels:
      app: database
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: backend
    ports:
    - protocol: TCP
      port: 80
EOF

# 应用NetworkPolicy
kubectl apply -f allow-backend-to-database.yaml

# 查看所有NetworkPolicy
kubectl get networkpolicy -n netpol-test
```

**测试效果:**

```bash
# frontend测试（应该失败）
kubectl exec frontend -n netpol-test -- curl -s --max-time 2 http://$DB_IP || echo "❌ BLOCKED"

# backend测试（应该成功）
kubectl exec backend -n netpol-test -- curl -s --max-time 2 http://$DB_IP && echo "✅ ALLOWED"

# attacker测试（应该失败）
kubectl exec attacker -n netpol-test -- wget -qO- --timeout=2 http://$DB_IP || echo "❌ BLOCKED"
```

**预期:** ✅ 只有backend可以访问database

**验证点:** ✅ 精确控制，只有backend可以访问database

**💡 知识点:**
- `ingress.from.podSelector` 选择允许的来源
- 基于标签匹配（`app=backend`）
- `ports` 限制允许的端口
- 多个NetworkPolicy规则是累加的（OR关系）

---

### Step 5: 命名空间级别隔离

测试跨命名空间的网络控制：

```bash
# 创建第二个命名空间并创建Pod
kubectl create namespace other-ns
kubectl run external-pod --image=busybox:1.28 -n other-ns --command -- sleep 3600
kubectl wait --for=condition=Ready pod external-pod -n other-ns --timeout=30s

# 测试访问（应该被阻止）
kubectl exec external-pod -n other-ns -- timeout 2 wget -qO- http://$DB_IP || echo "❌ BLOCKED"
```

**创建允许特定命名空间的规则:**

```bash
cat > allow-from-namespace.yaml <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-from-other-ns
  namespace: netpol-test
spec:
  podSelector:
    matchLabels:
      app: backend
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: other-ns
EOF

kubectl label namespace other-ns name=other-ns
kubectl apply -f allow-from-namespace.yaml

# 测试访问backend
BACKEND_IP=$(kubectl get pod backend -n netpol-test -o jsonpath='{.status.podIP}')
kubectl exec external-pod -n other-ns -- wget -qO- --timeout=2 http://$BACKEND_IP
```

**验证点:** ✅ 可以基于命名空间标签控制访问

**💡 知识点:** `namespaceSelector`实现多租户环境的网络隔离

---

### Step 6: Egress规则 - 出站流量控制

限制frontend的出站流量：

```bash
cat > frontend-egress.yaml <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: frontend-egress
  namespace: netpol-test
spec:
  podSelector:
    matchLabels:
      app: frontend
  policyTypes:
  - Egress
  egress:
  - to:
    - podSelector:
        matchLabels:
          app: backend
    ports:
    - protocol: TCP
      port: 80
EOF

# 应用NetworkPolicy
kubectl apply -f frontend-egress.yaml

# 测试效果
BACKEND_IP=$(kubectl get pod backend -n netpol-test -o jsonpath='{.status.podIP}')
echo "Testing frontend → backend:"
kubectl exec frontend -n netpol-test -- curl -s --max-time 2 http://$BACKEND_IP

echo "Testing frontend → database:"
kubectl exec frontend -n netpol-test -- curl -s --max-time 2 http://$DB_IP || echo "❌ BLOCKED"
```

**预期输出:**
```
✅ frontend → backend: 成功
❌ frontend → database: BLOCKED
```

**验证点:** ✅ Egress规则限制出站流量

**💡 知识点:**
- `policyTypes: [Egress]` 控制出站流量
- `egress.to` 定义允许访问的目标
- Egress规则用于防止数据泄露
- 可以同时使用Ingress和Egress

---

### Step 7: 验证策略效果

查看并测试所有NetworkPolicy规则：

```bash
# 查看所有NetworkPolicy
kubectl get networkpolicy -n netpol-test

# 快速测试矩阵
echo "=== Network Policy Test Matrix ==="
kubectl exec frontend -n netpol-test -- curl -s --max-time 2 http://$BACKEND_IP && echo "1. frontend→backend: ✅" || echo "1. frontend→backend: ❌"
kubectl exec frontend -n netpol-test -- curl -s --max-time 2 http://$DB_IP && echo "2. frontend→database: ✅" || echo "2. frontend→database: ❌"
kubectl exec backend -n netpol-test -- curl -s --max-time 2 http://$DB_IP && echo "3. backend→database: ✅" || echo "3. backend→database: ❌"
kubectl exec attacker -n netpol-test -- wget -qO- --timeout=2 http://$DB_IP && echo "4. attacker→database: ✅" || echo "4. attacker→database: ❌"
```

**预期:** frontend→backend✅, backend→database✅, 其他全部❌

**💡 知识点:** NetworkPolicy规则是累加的，使用测试矩阵验证正确性

---

## ✅ 验证清单

- [ ] 理解默认网络行为（全通）
- [ ] 成功创建deny-all NetworkPolicy
- [ ] 成功配置Ingress规则允许backend访问database
- [ ] 配置命名空间级别隔离
- [ ] 配置Egress规则控制出站流量
- [ ] 理解基于标签选择器的流量控制机制

---

## 🔧 故障排查

### 问题1: NetworkPolicy不生效

**原因:** 策略配置错误或Pod标签不匹配

**解决:** 检查NetworkPolicy配置和Pod标签

```bash
# 检查NetworkPolicy配置
kubectl describe networkpolicy -n netpol-test

# 检查Pod标签是否匹配
kubectl get pod -n netpol-test --show-labels

# 验证选择器匹配
kubectl get networkpolicy -n netpol-test -o yaml | grep -A 3 podSelector

# 检查CNI插件（K3s Flannel完全支持NetworkPolicy）
ls /etc/cni/net.d/

# 如果确认配置正确但仍不生效，重启CoreDNS和相关Pod
kubectl rollout restart deployment coredns -n kube-system
kubectl delete pod --all -n netpol-test
```

---

### 问题2: 标签选择器不匹配

**原因:** 标签配置错误

**解决:** 检查Pod标签和NetworkPolicy选择器是否匹配
```bash
kubectl get pod -n netpol-test --show-labels
kubectl get networkpolicy -n netpol-test -o yaml | grep -A 3 matchLabels
```

---

## 🧪 扩展练习

### 默认拒绝所有流量

在命名空间级别设置默认拒绝（零信任模式）：

```bash
cat > default-deny-all.yaml <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: netpol-test
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
EOF

kubectl apply -f default-deny-all.yaml
```

**注意:** 这会阻止所有流量，需要逐个添加允许规则

---

## 📖 知识总结

### NetworkPolicy核心概念

**工作原理:** 默认全通 → 应用策略 → 隔离模式（白名单） → 显式允许规则

**关键字段:**
- `podSelector`: 选择要保护的Pod（基于标签）
- `policyTypes`: Ingress（入站）/ Egress（出站）
- `ingress.from`: 允许的来源（podSelector/namespaceSelector/ipBlock）
- `egress.to`: 允许的目标
- `ports`: 允许的端口

**最佳实践:**
1. 默认拒绝策略 - 先拒绝，再允许
2. 最小权限原则 - 只开放必需的访问
3. 分层防护 - 应用层+网络层+基础设施层
4. 标签管理 - 统一标签规范
5. 定期审计 - 检查策略有效性

---

## 🧹 清理环境

```bash
# 删除命名空间（包含所有资源）
kubectl delete namespace netpol-test other-ns

# 删除配置文件
rm -f deny-all-to-database.yaml allow-backend-to-database.yaml
rm -f allow-from-namespace.yaml frontend-egress.yaml default-deny-all.yaml

# 验证清理
kubectl get namespace | grep netpol
```

---

## 📚 参考资料

- [Kubernetes NetworkPolicy官方文档](https://kubernetes.io/docs/concepts/services-networking/network-policies/)
- [NetworkPolicy配方集](https://github.com/ahmetb/kubernetes-network-policy-recipes)
- [Calico NetworkPolicy](https://docs.projectcalico.org/security/kubernetes-network-policy)

---

**实验5完成！** 🎉

继续下一个实验前，确保理解：
- NetworkPolicy的工作原理
- Ingress和Egress规则配置
- 基于标签选择器的流量控制
- 默认拒绝（白名单）模式
- CNI插件的影响

祝你学习愉快！🚀
