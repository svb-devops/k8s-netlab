# 实验1: Kubernetes网络模型基础验证

## 📚 实验信息

- **难度**: ⭐⭐ (入门)
- **时长**: 30分钟
- **环境**: K3s单节点集群
- **前置**: 已有可用的K8s集群

## 🎯 学习目标

通过本实验，你将：
1. 理解Kubernetes三大网络基本要求
2. 验证Pod IP地址分配机制
3. 测试Pod之间的直接通信
4. 观察Pod的网络命名空间
5. 理解"IP-per-Pod"模型

## 📖 前置知识

- Linux基础网络命令 (ip, ping)
- Docker容器基础概念
- Kubernetes Pod基本概念

## 🐳 实验镜像说明

本实验使用两种镜像：

### busybox:1.28
- **用途**: 网络连通性测试
- **大小**: ~1-2MB
- **包含**: ping, ip, netstat, traceroute, nslookup等工具
- **优势**: 轻量级，专为测试设计
- **使用场景**: Step 1-3, 5-7

### nginx
- **用途**: HTTP服务测试
- **大小**: ~50MB
- **包含**: nginx web服务器
- **优势**: 真实应用场景
- **使用场景**: Step 4 (Node到Pod HTTP测试)

**💡 最佳实践:**
- 网络层测试用busybox（ICMP, TCP/IP）
- 应用层测试用nginx（HTTP）
- 这是生产环境的标准做法

**🔧 高级选项:**
- 如需更强大的网络诊断工具（tcpdump, iperf3等）
- 可以使用: `nicolaka/netshoot`
- 但镜像较大（~300MB），拉取时间较长

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

### Step 1: 创建测试Pod

**选择A: 使用busybox（推荐用于网络测试）**
```bash
# 创建busybox Pod（包含完整网络工具）
kubectl run test-pod-1 --image=busybox:1.28 --command -- sleep 3600

# 等待Pod运行
kubectl wait --for=condition=Ready pod/test-pod-1 --timeout=60s

# 查看Pod状态
kubectl get pod test-pod-1 -o wide
```

**选择B: 使用nginx（如果要测试HTTP服务）**
```bash
# 创建nginx Pod
kubectl run nginx-1 --image=nginx

# 等待Pod运行
kubectl wait --for=condition=Ready pod/nginx-1 --timeout=60s

# 查看Pod状态
kubectl get pod nginx-1 -o wide
```

**本实验推荐选择A（busybox），因为后续步骤需要网络工具。**

**预期输出:**
```
NAME          READY   STATUS    RESTARTS   AGE   IP           NODE
test-pod-1    1/1     Running   0          10s   10.42.0.15   node-1
```

**验证点:** ✅ Pod获得了唯一的IP地址 (10.42.x.x 网段)

**🔍 知识点:**
- busybox是轻量级Linux工具集镜像（1-2MB）
- 包含ping, ip, netstat, traceroute等网络工具
- 常用于Kubernetes网络调试
- `sleep 3600`让容器保持运行1小时，方便测试

### Step 2: 创建第二个测试Pod
```bash
# 创建第二个busybox Pod
kubectl run test-pod-2 --image=busybox:1.28 --command -- sleep 3600

# 等待运行
kubectl wait --for=condition=Ready pod/test-pod-2 --timeout=60s

# 查看两个Pod的IP
kubectl get pod -o wide
```

**预期输出:**
```
NAME          READY   STATUS    IP
test-pod-1    1/1     Running   10.42.0.15
test-pod-2    1/1     Running   10.42.0.16
```

**验证点:** ✅ 每个Pod都有独立IP，在同一网段

### Step 3: 验证Pod间直接通信 (无NAT)
```bash
# 获取test-pod-2的IP
POD2_IP=$(kubectl get pod test-pod-2 -o jsonpath='{.status.podIP}')

# 从test-pod-1 ping test-pod-2
kubectl exec test-pod-1 -- ping -c 3 $POD2_IP

# 反向测试
POD1_IP=$(kubectl get pod test-pod-1 -o jsonpath='{.status.podIP}')
kubectl exec test-pod-2 -- ping -c 3 $POD1_IP
```

**预期输出:**
```
PING 10.42.0.16 (10.42.0.16): 56 data bytes
64 bytes from 10.42.0.16: seq=0 ttl=64 time=0.089 ms
64 bytes from 10.42.0.16: seq=1 ttl=64 time=0.052 ms
64 bytes from 10.42.0.16: seq=2 ttl=64 time=0.048 ms

--- 10.42.0.16 ping statistics ---
3 packets transmitted, 3 packets received, 0% packet loss
```

**验证点:** ✅ Pod之间可以直接通过IP通信，无需NAT转换

**🔍 知识点:**
- TTL=64表示在同一网络内，未经过路由跳转
- 延迟<1ms说明是本地通信（同节点）
- 0%丢包率证明网络稳定

### Step 4: 测试Node到Pod的通信

**准备工作：创建nginx Pod用于HTTP测试**
```bash
# 创建nginx Pod（用于HTTP测试）
kubectl run nginx-test --image=nginx

# 等待运行
kubectl wait --for=condition=Ready pod/nginx-test --timeout=60s

# 获取nginx Pod IP
NGINX_IP=$(kubectl get pod nginx-test -o jsonpath='{.status.podIP}')
echo "Nginx Pod IP: $NGINX_IP"
```

**从Node直接访问Pod**
```bash
# 从Node访问Pod的HTTP服务
curl -s http://$NGINX_IP | head -n 5
```

**预期输出:**
```
<!DOCTYPE html>
<html>
<head>
<title>Welcome to nginx!</title>
```

**验证点:** ✅ Node可以直接访问Pod的IP

**🔍 知识点:**
- 这证明了Kubernetes网络模型的第二个要求
- "所有Node可以与所有Pod通信，无需NAT"
- 在生产环境中，这允许kubelet直接健康检查Pod

### Step 5: 查看Pod的网络接口
```bash
# 进入test-pod-1查看网络配置
kubectl exec test-pod-1 -- ip addr show

# 查看路由表
kubectl exec test-pod-1 -- ip route
```

**预期输出:**
```
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536
    inet 127.0.0.1/8 scope host lo
3: eth0@if10: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1450
    inet 10.42.0.15/24 brd 10.42.0.255 scope global eth0
```

**验证点:** ✅ Pod有独立的网络接口 eth0

### Step 6: 验证Pod到外部的通信
```bash
# 从busybox Pod访问外网
kubectl exec test-pod-1 -- ping -c 3 8.8.8.8

# 测试DNS解析
kubectl exec test-pod-1 -- nslookup kubernetes.default
```

**预期输出:**
```
PING 8.8.8.8 (8.8.8.8): 56 data bytes
64 bytes from 8.8.8.8: seq=0 ttl=115 time=10.2 ms
```

**验证点:** ✅ Pod可以访问外网

### Step 7: 观察网络命名空间
```bash
# 在Node上列出网络命名空间
sudo ip netns list

# 查看veth pair
ip link show type veth
```

**预期输出:**
```
cni-xxx (id: 0)
cni-yyy (id: 1)

10: veth1234@if3: <BROADCAST,MULTICAST,UP>
11: veth5678@if3: <BROADCAST,MULTICAST,UP>
```

**验证点:** ✅ 每个Pod对应一个网络命名空间和veth pair

## ✅ 验证清单

实验完成后，确认以下要点：

- [ ] 每个Pod获得唯一的IP地址
- [ ] Pod之间可以直接ping通 (使用IP)
- [ ] Node可以直接访问Pod IP
- [ ] Pod有独立的网络命名空间
- [ ] Pod内可以看到eth0网络接口
- [ ] Pod可以访问外网
- [ ] 观察到veth pair的存在

## 🔧 故障排查

### 问题1: Pod一直处于Pending状态

**原因:** 节点资源不足或镜像拉取失败

**解决:**
```bash
# 查看Pod详情
kubectl describe pod test-pod-1

# 查看事件
kubectl get events --sort-by=.metadata.creationTimestamp
```

### 问题2: Pod之间无法ping通

**原因:** CNI插件配置问题或防火墙规则

**解决:**
```bash
# 检查CNI插件
ls /etc/cni/net.d/

# 查看Pod日志
kubectl logs test-pod-1

# 检查iptables规则
sudo iptables -L -n | grep FORWARD
```

### 问题3: 无法从Node访问Pod

**原因:** 路由表配置问题

**解决:**
```bash
# 查看路由表
ip route

# 应该有到Pod网段的路由
# 10.42.0.0/16 via ...
```

## 🧪 扩展练习

### 1. 多Pod通信测试
- 创建5个Pod，测试所有Pod之间的连通性
- 使用for循环自动化测试

### 2. 网络性能基准
- 使用iperf3测量Pod间带宽
- 对比Pod到Node和Pod到Pod的延迟

### 3. 探索CNI配置
- 查看/etc/cni/net.d/下的配置文件
- 理解K3s使用的CNI插件 (Flannel)

## 📚 知识总结

### Kubernetes网络三大基本要求

1. **所有Pod可以与所有其他Pod通信，无需NAT**
   - ✅ Step 3 验证

2. **所有Node可以与所有Pod通信，无需NAT**
   - ✅ Step 4 验证

3. **Pod看到的自己的IP与其他Pod看到的一致**
   - ✅ Step 5 验证

### IP-per-Pod模型

- 每个Pod获得唯一的IP地址
- Pod内所有容器共享这个IP和网络命名空间
- 简化了网络模型，类似传统的虚拟机

### 网络实现原理

- 使用网络命名空间隔离
- veth pair连接Pod和主机
- 网桥或路由实现Pod间通信
- CNI插件负责配置网络

## 🧹 清理环境

```bash
# 删除测试Pod
kubectl delete pod test-pod-1 test-pod-2 nginx-test

# 验证清理
kubectl get pod
```

**注意:** 实验2和3会创建新的资源，建议清理干净。

## 📖 参考资料

- [Kubernetes网络模型官方文档](https://kubernetes.io/docs/concepts/cluster-administration/networking/)
- [CNI规范](https://github.com/containernetworking/cni)
- [Linux网络命名空间](https://man7.org/linux/man-pages/man7/network_namespaces.7.html)
- [K3s网络架构](https://docs.k3s.io/networking)

---

**实验1完成！** 🎉

继续下一个实验前，确保理解：
- Pod网络模型的三大要求
- IP-per-Pod的含义
- 网络命名空间的作用
