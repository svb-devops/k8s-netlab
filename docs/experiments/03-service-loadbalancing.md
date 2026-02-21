# 实验3: Service负载均衡机制

## 📚 实验信息

- **难度**: ⭐⭐⭐ (中级)
- **时长**: 45分钟
- **环境**: K3s单节点集群
- **前置**: 完成实验1和2，理解Pod网络

## 🎯 学习目标

通过本实验，你将：
1. 理解Service的三种类型 (ClusterIP, NodePort, LoadBalancer)
2. 掌握ClusterIP的工作原理
3. 分析kube-proxy的iptables规则
4. 测试Service的负载均衡效果
5. 观察Endpoint的动态更新

## 📖 前置知识

- 完成实验1和2
- 理解Pod和Deployment概念
- 了解基本的iptables知识
- 理解负载均衡概念

## 🐳 实验镜像说明

本实验使用的镜像：

### nginx
- **用途**: HTTP Web服务，演示负载均衡
- **场景**: Deployment应用Pod，Step 1-9
- **原因**: 真实的Web应用场景
- **优势**:
  - 提供HTTP服务便于测试
  - 生产环境常见应用
  - 可以通过HTTP请求验证负载均衡

### busybox:1.28
- **用途**: DNS解析测试
- **场景**: Step 10 临时测试Pod
- **工具**: nslookup, wget等

**💡 Service实验特点:**
- 需要真实应用服务（非测试工具）
- nginx是最佳选择（轻量、稳定、常见）
- 通过HTTP请求路径验证Service工作机制
- 这是生产环境的标准做法

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

## 🔬 实验步骤

### Step 1: 创建多副本Deployment
```bash
# 创建nginx Deployment，3个副本
kubectl create deployment nginx-app --image=nginx --replicas=3

# 等待所有Pod运行
kubectl wait --for=condition=Ready pod -l app=nginx-app --timeout=120s

# 查看Pod和IP
kubectl get pod -l app=nginx-app -o wide
```

**预期输出:**
```
NAME                        READY   STATUS    RESTARTS   AGE   IP
nginx-app-xxx-aaa          1/1     Running   0          10s   10.42.0.25
nginx-app-xxx-bbb          1/1     Running   0          10s   10.42.0.26
nginx-app-xxx-ccc          1/1     Running   0          10s   10.42.0.27
```

**验证点:** ✅ 3个Pod运行，各有独立IP

---

### Step 2: 创建ClusterIP Service
```bash
# 创建Service暴露80端口
kubectl expose deployment nginx-app --port=80 --target-port=80 --name=nginx-service

# 查看Service详情
kubectl get svc nginx-service

# 查看Service的详细信息
kubectl describe svc nginx-service
```

**预期输出:**
```
NAME            TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)
nginx-service   ClusterIP   10.43.123.45    <none>        80/TCP

Endpoints: 10.42.0.25:80,10.42.0.26:80,10.42.0.27:80
```

**验证点:** ✅ Service获得ClusterIP，Endpoints指向3个Pod

---

### Step 3: 测试Service访问
```bash
# 获取Service的ClusterIP
SVC_IP=$(kubectl get svc nginx-service -o jsonpath='{.spec.clusterIP}')
echo "Service IP: $SVC_IP"

# 从Node直接访问Service
curl -s http://$SVC_IP | grep title

# 多次访问测试负载均衡
for i in {1..10}; do
  curl -s http://$SVC_IP | grep title
done
```

**预期输出:**
```
<title>Welcome to nginx!</title>
<title>Welcome to nginx!</title>
...
```

**验证点:** ✅ 可以通过ClusterIP访问Service

---

### Step 4: 给Pod添加标识以验证负载均衡
```bash
# 获取所有Pod名称
POD_NAMES=$(kubectl get pod -l app=nginx-app -o jsonpath='{.items[*].metadata.name}')

# 为每个Pod的nginx添加自定义标识
for POD in $POD_NAMES; do
  kubectl exec $POD -- bash -c "echo 'Pod: $POD' > /usr/share/nginx/html/pod.txt"
done

# 测试访问不同Pod
for i in {1..10}; do
  curl -s http://$SVC_IP/pod.txt
done
```

**预期输出:**
```
Pod: nginx-app-xxx-aaa
Pod: nginx-app-xxx-bbb
Pod: nginx-app-xxx-ccc
Pod: nginx-app-xxx-aaa
...
```

**验证点:** ✅ 请求被分发到不同Pod，实现负载均衡

---

### Step 5: 查看Endpoint对象
```bash
# 查看Endpoint
kubectl get endpoints nginx-service

# 查看详细信息
kubectl describe endpoints nginx-service

# 以YAML格式查看
kubectl get endpoints nginx-service -o yaml
```

**预期输出:**
```
NAME            ENDPOINTS
nginx-service   10.42.0.25:80,10.42.0.26:80,10.42.0.27:80

Subsets:
  Addresses:
    10.42.0.25 (Pod: nginx-app-xxx-aaa)
    10.42.0.26 (Pod: nginx-app-xxx-bbb)
    10.42.0.27 (Pod: nginx-app-xxx-ccc)
  Ports:
    Port: 80
```

**验证点:** ✅ Endpoint包含所有Pod的IP和端口

---

### Step 6: 分析kube-proxy的iptables规则
```bash
# 查看Service相关的NAT规则
sudo iptables -t nat -L KUBE-SERVICES -n -v | grep nginx-service

# 查看具体的DNAT规则
sudo iptables -t nat -L -n | grep 10.43.123.45

# 查看Service的负载均衡链
SVC_CHAIN=$(sudo iptables-save | grep "KUBE-SVC" | grep nginx | head -1 | awk '{print $2}')
sudo iptables -t nat -L $SVC_CHAIN -n -v
```

**预期输出:**
```
Chain KUBE-SERVICES:
pkts bytes target     prot opt in     out     source      destination
   0     0 KUBE-SVC-XXX  tcp  --  *      *   0.0.0.0/0   10.43.123.45  /* default/nginx-service */

Chain KUBE-SVC-XXX:
   0     0 KUBE-SEP-AAA  all  --  *      *   0.0.0.0/0   0.0.0.0/0    /* statistic mode random probability 0.33 */
   0     0 KUBE-SEP-BBB  all  --  *      *   0.0.0.0/0   0.0.0.0/0    /* statistic mode random probability 0.50 */
   0     0 KUBE-SEP-CCC  all  --  *      *   0.0.0.0/0   0.0.0.0/0
```

**验证点:** ✅ 理解Service通过iptables实现负载均衡

---

### Step 7: 测试Endpoint动态更新
```bash
# 扩容到5个副本
kubectl scale deployment nginx-app --replicas=5

# 等待新Pod启动
kubectl wait --for=condition=Ready pod -l app=nginx-app --timeout=60s

# 查看Endpoint自动更新
kubectl get endpoints nginx-service

# 查看新的iptables规则
sudo iptables-save | grep "KUBE-SVC" | grep nginx | head -1 | awk '{print $2}' | xargs -I {} sudo iptables -t nat -L {} -n
```

**预期输出:**
```
NAME            ENDPOINTS
nginx-service   10.42.0.25:80,10.42.0.26:80,10.42.0.27:80,10.42.0.28:80,10.42.0.29:80

iptables链现在有5个规则，每个概率0.2
```

**验证点:** ✅ Endpoint动态更新，负载均衡规则自动调整

---

### Step 8: 缩容测试
```bash
# 缩容到2个副本
kubectl scale deployment nginx-app --replicas=2

# 等待Pod终止
sleep 10

# 查看Endpoint
kubectl get endpoints nginx-service

# 测试Service仍然可用
for i in {1..5}; do
  curl -s http://$SVC_IP/pod.txt
done
```

**预期输出:**
```
NAME            ENDPOINTS
nginx-service   10.42.0.25:80,10.42.0.26:80

Pod: nginx-app-xxx-aaa
Pod: nginx-app-xxx-bbb
Pod: nginx-app-xxx-aaa
...
```

**验证点:** ✅ 缩容后Service自动更新，只转发到剩余Pod

---

### Step 9: 创建NodePort Service (可选)
```bash
# 创建NodePort类型的Service
kubectl expose deployment nginx-app --port=80 --target-port=80 --name=nginx-nodeport --type=NodePort

# 查看NodePort
kubectl get svc nginx-nodeport

# 获取NodePort端口号
NODE_PORT=$(kubectl get svc nginx-nodeport -o jsonpath='{.spec.ports[0].nodePort}')
echo "NodePort: $NODE_PORT"

# 从外部访问 (使用Node IP)
NODE_IP=$(hostname -I | awk '{print $1}')
curl http://$NODE_IP:$NODE_PORT | grep title
```

**预期输出:**
```
NAME             TYPE       CLUSTER-IP     PORT(S)
nginx-nodeport   NodePort   10.43.234.56   80:32456/TCP

NodePort: 32456

<title>Welcome to nginx!</title>
```

**验证点:** ✅ NodePort允许通过节点IP访问Service

---

### Step 10: 使用Service DNS名称
```bash
# 创建临时Pod用于测试DNS
kubectl run test-client --image=busybox:1.28 --rm -it --restart=Never -- sh

# 在Pod内执行以下命令:
# nslookup nginx-service
# wget -qO- http://nginx-service
# exit

# 或在命令行直接测试
kubectl run test-client --image=busybox:1.28 --rm -it --restart=Never -- nslookup nginx-service
```

**预期输出:**
```
Server:    10.43.0.10
Address 1: 10.43.0.10 kube-dns.kube-system.svc.cluster.local

Name:      nginx-service
Address 1: 10.43.123.45 nginx-service.default.svc.cluster.local
```

**验证点:** ✅ Service可以通过DNS名称访问

**💡 知识点:**
- Service自动获得DNS记录：`<service-name>.<namespace>.svc.cluster.local`
- 简短形式：同命名空间内可以直接用service名称
- CoreDNS负责Service的DNS解析
- 这是Kubernetes服务发现的核心机制

---

## ✅ 验证清单

实验完成后，确认以下要点：

- [ ] 成功创建多副本Deployment
- [ ] Service获得ClusterIP
- [ ] 通过ClusterIP可以访问Pod
- [ ] 验证了负载均衡效果
- [ ] 理解Endpoint对象的作用
- [ ] 查看了iptables负载均衡规则
- [ ] 测试了扩缩容的动态更新
- [ ] (可选) 创建了NodePort Service
- [ ] 验证了Service DNS解析

## 🔧 故障排查

### 问题1: Service无法访问

**原因:** kube-proxy未运行或iptables规则异常

**解决:**
```bash
# 检查kube-proxy
kubectl get pod -n kube-system | grep proxy

# 查看kube-proxy日志
kubectl logs -n kube-system -l k8s-app=kube-proxy --tail=50

# 检查iptables
sudo iptables -t nat -L KUBE-SERVICES -n
```

---

### 问题2: 负载均衡不均匀

**原因:** 这是正常的，iptables使用随机概率分发

**说明:**
```
iptables的statistic模块使用随机概率
不是轮询(Round Robin)，是概率分发
短期内可能不均匀，长期趋于均衡
```

---

### 问题3: Endpoint未自动更新

**原因:** Pod标签不匹配或网络问题

**解决:**
```bash
# 检查Pod标签
kubectl get pod -l app=nginx-app --show-labels

# 检查Service selector
kubectl get svc nginx-service -o yaml | grep -A 3 selector

# 确保标签匹配
```

---

## 🧪 扩展练习

### 1. 深入研究iptables规则
```bash
# 完整导出iptables规则
sudo iptables-save > iptables-rules.txt

# 分析KUBE-SERVICES, KUBE-SVC-*, KUBE-SEP-*链
# 理解每个链的作用
```

### 2. 测试Session Affinity
```bash
# 创建有会话亲和性的Service
kubectl create service clusterip nginx-sticky --tcp=80:80

# 设置sessionAffinity
kubectl patch svc nginx-sticky -p '{"spec":{"sessionAffinity":"ClientIP"}}'

# 测试相同客户端是否访问同一Pod
```

### 3. 监控Service性能
```bash
# 使用ab (Apache Bench) 压测
sudo apt-get install apache2-utils -y
ab -n 1000 -c 10 http://$SVC_IP/
```

---

## 📚 知识总结

### Service类型

1. **ClusterIP** (默认)
   - 分配集群内部IP
   - 只能在集群内访问
   - 用于内部服务通信

2. **NodePort**
   - 在ClusterIP基础上
   - 在每个Node打开指定端口
   - 外部可通过 NodeIP:NodePort 访问

3. **LoadBalancer**
   - 在NodePort基础上
   - 请求云厂商创建负载均衡器
   - 提供外部可访问的IP

### Service工作原理
```
客户端
  ↓
ClusterIP:80 (虚拟IP，iptables DNAT)
  ↓
iptables规则链 (KUBE-SERVICES → KUBE-SVC-XXX)
  ↓
随机选择一个后端 (KUBE-SEP-AAA/BBB/CCC)
  ↓
DNAT到Pod IP:Port
  ↓
Pod (10.42.0.25:80 / 10.42.0.26:80 / 10.42.0.27:80)
```

### kube-proxy模式

K3s默认使用 **iptables** 模式:
- 通过iptables规则实现负载均衡
- 使用random概率分发
- 无需额外进程转发数据
- 性能好，延迟低

其他模式:
- **IPVS**: 更高性能，支持更多算法
- **userspace**: 最早的模式，已废弃

### Endpoint Controller

- 监听Pod和Service变化
- 自动更新Endpoint对象
- Endpoint = Service后端Pod的IP:Port列表
- kube-proxy根据Endpoint更新iptables

---

## 🧹 清理环境
```bash
# 删除Service
kubectl delete svc nginx-service nginx-nodeport --ignore-not-found=true

# 删除Deployment
kubectl delete deployment nginx-app

# 验证清理
kubectl get svc,deploy,pod
```

**注意:** 实验4-11会创建新的资源，建议清理干净。

---

## 📖 参考资料

- [Service官方文档](https://kubernetes.io/docs/concepts/services-networking/service/)
- [kube-proxy模式对比](https://kubernetes.io/docs/reference/networking/virtual-ips/)
- [Endpoint Slices](https://kubernetes.io/docs/concepts/services-networking/endpoint-slices/)
- [iptables教程](https://www.frozentux.net/iptables-tutorial/iptables-tutorial.html)

---

**实验3完成！** 🎉

继续下一批实验前，确保理解：
- Service的三种类型及使用场景
- ClusterIP如何通过iptables实现负载均衡
- Endpoint的动态更新机制
- kube-proxy的工作原理

---

**今天上午的实验文档创建完成！**

接下来：
1. 在实际K3s环境测试这三个实验
2. 验证所有命令可执行
3. 截图关键步骤
4. 修正任何问题
