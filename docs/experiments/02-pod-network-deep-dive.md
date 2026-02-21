# 实验2: Pod网络实现原理深入探索

## 📚 实验信息

- **难度**: ⭐⭐⭐ (中级)
- **时长**: 45分钟
- **环境**: K3s单节点集群
- **前置**: 完成实验1，理解基本Pod网络

## 🎯 学习目标

通过本实验，你将：
1. 理解CNI插件的工作流程
2. 观察veth pair的创建和连接
3. 分析Linux网桥的作用
4. 追踪数据包在Pod间的转发路径
5. 深入理解Pod网络的底层实现

## 📖 前置知识

- 完成实验1
- Linux网络基础 (veth, bridge, route)
- 理解网络命名空间概念
- 基本的tcpdump使用

## 🐳 实验镜像说明

本实验使用的镜像：

### busybox:1.28
- **用途**: 网络测试和诊断
- **工具**: ip, ping, netstat, nslookup等
- **场景**: Step 2-8 网络层测试

### networkstatic/iperf3
- **用途**: 网络性能测试
- **工具**: iperf3
- **场景**: Step 9 性能测试（可选）

**💡 说明:**
- 本实验重点是观察网络实现原理
- 大部分诊断在Node上进行（如tcpdump）
- Pod主要用于生成测试流量

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

### Step 1: 查看CNI配置
```bash
# 查看CNI配置目录
ls -la /etc/cni/net.d/

# 查看CNI配置内容 (K3s使用Flannel)
sudo cat /etc/cni/net.d/*.conflist 2>/dev/null || sudo cat /etc/cni/net.d/*.conf

# 查看CNI插件二进制文件
ls -la /opt/cni/bin/
```

**预期输出:**
```
/etc/cni/net.d/:
10-flannel.conflist

{
  "name": "cbr0",
  "cniVersion": "0.3.1",
  "plugins": [
    {
      "type": "flannel",
      "delegate": {
        "hairpinMode": true,
        "isDefaultGateway": true
      }
    }
  ]
}
```

**验证点:** ✅ 了解K3s使用的CNI插件配置

---

### Step 2: 创建测试Pod并观察网络设置
```bash
# 创建测试Pod（使用busybox以便后续网络诊断）
kubectl run test-pod --image=busybox:1.28 --command -- sleep 3600

# 等待Pod运行
kubectl wait --for=condition=Ready pod/test-pod --timeout=60s

# 获取Pod详细信息
kubectl get pod test-pod -o yaml | grep -A 5 "podIP"
```

**预期输出:**
```
podIP: 10.42.0.20
podIPs:
- ip: 10.42.0.20
```

**💡 说明:**
- 使用busybox而非nginx，因为后续步骤需要ip、traceroute等工具
- busybox包含完整的网络诊断工具集

---

### Step 3: 查找Pod对应的网络命名空间
```bash
# 获取Pod的容器ID
POD_ID=$(kubectl get pod test-pod -o jsonpath='{.status.containerStatuses[0].containerID}' | cut -d'/' -f3)
echo "Container ID: $POD_ID"

# 查找容器进程
CONTAINER_PID=$(sudo crictl inspect $POD_ID 2>/dev/null | jq -r '.info.pid' || echo "使用docker则运行: docker inspect -f '{{.State.Pid}}' $POD_ID")
echo "Container PID: $CONTAINER_PID"

# 查看该进程的网络命名空间
sudo ls -la /proc/$CONTAINER_PID/ns/net
```

**预期输出:**
```
Container ID: abc123...
Container PID: 12345
lrwxrwxrwx 1 root root 0 ... /proc/12345/ns/net -> net:[4026532123]
```

**验证点:** ✅ 每个Pod有独立的网络命名空间

---

### Step 4: 观察veth pair
```bash
# 在主机上查看所有veth接口
ip link show type veth

# 查看特定Pod的网络接口 (进入Pod查看)
kubectl exec test-pod -- ip link show

# 找到veth pair的对应关系
# Pod内看到的eth0@ifXX，XX就是主机侧veth的index
kubectl exec test-pod -- ip link show eth0
```

**预期输出:**
```
主机侧:
10: veth12345@if3: <BROADCAST,MULTICAST,UP> mtu 1450
    link/ether aa:bb:cc:dd:ee:ff

Pod内:
3: eth0@if10: <BROADCAST,MULTICAST,UP> mtu 1450
    link/ether 00:11:22:33:44:55
    inet 10.42.0.20/24
```

**验证点:** ✅ 理解veth pair是成对出现的虚拟网卡

---

### Step 5: 检查Linux网桥
```bash
# K3s/Flannel使用的可能是cni0网桥或直接路由
# 查看网桥 (如果存在)
ip link show type bridge

# 或查看具体的cni0
ip addr show cni0 2>/dev/null || echo "K3s可能使用host-gw模式，无网桥"

# 查看网桥连接的接口
bridge link show 2>/dev/null || brctl show 2>/dev/null
```

**预期输出 (如果有网桥):**
```
4: cni0: <BROADCAST,MULTICAST,UP> mtu 1450
    inet 10.42.0.1/24 brd 10.42.0.255

bridge link show:
10: veth12345@if3: master cni0
```

**验证点:** ✅ 理解网桥如何连接多个veth pair

---

### Step 6: 分析路由表
```bash
# 查看主机路由表
ip route

# 查看Pod内的路由表
kubectl exec test-pod -- ip route

# 查看到Pod网段的具体路由
ip route show | grep 10.42
```

**预期输出:**
```
主机路由:
10.42.0.0/24 dev cni0 proto kernel scope link src 10.42.0.1
# 或 (host-gw模式)
10.42.0.0/24 dev flannel.1 proto kernel scope link

Pod内路由:
default via 10.42.0.1 dev eth0
10.42.0.0/24 dev eth0 proto kernel scope link src 10.42.0.20
```

**验证点:** ✅ 理解数据包如何通过路由表转发

---

### Step 7: 使用tcpdump抓包验证

**注意:** tcpdump需要特权权限，建议在Node上执行。

```bash
# 创建第二个测试Pod
kubectl run test-pod-2 --image=busybox:1.28 --command -- sleep 3600
kubectl wait --for=condition=Ready pod/test-pod-2 --timeout=60s

# 获取test-pod-2的IP
POD2_IP=$(kubectl get pod test-pod-2 -o jsonpath='{.status.podIP}')

# 在主机上抓包 (新终端或后台运行)
# K3s的CNI接口通常是 cni0 或 flannel.1
sudo tcpdump -i cni0 -n icmp 2>/dev/null || sudo tcpdump -i flannel.1 -n icmp &

# 在当前终端测试连通性
kubectl exec test-pod -- ping -c 3 $POD2_IP

# 停止tcpdump (如果后台运行)
sudo pkill tcpdump
```

**预期输出:**
```
tcpdump显示:
10:30:45.123456 IP 10.42.0.20 > 10.42.0.21: ICMP echo request
10:30:45.123789 IP 10.42.0.21 > 10.42.0.20: ICMP echo reply
```

**验证点:** ✅ 验证数据包通过主机网络设施转发

**💡 知识点:**
- tcpdump在Node上运行可以看到所有Pod间流量
- `-i cni0` 指定网桥接口（如果使用网桥模式）
- `-i flannel.1` 指定flannel VXLAN接口（如果使用overlay模式）
- `-n` 不解析域名，显示IP地址

---

### Step 8: 追踪数据包路径
```bash
# 在Pod内追踪到另一个Pod的路径
# busybox的traceroute可能不存在，使用ping测试
kubectl exec test-pod -- ping -c 1 $POD2_IP

# 查看ARP表 (Pod内)
kubectl exec test-pod -- ip neigh

# 查看主机的ARP表
ip neigh | grep 10.42
```

**预期输出:**
```
PING 10.42.0.21 (10.42.0.21): 56 data bytes
64 bytes from 10.42.0.21: seq=0 ttl=64 time=0.089 ms

ARP表 (Pod内):
10.42.0.1 dev eth0 lladdr aa:bb:cc:dd:ee:ff REACHABLE
```

**验证点:** ✅ 理解数据包经过网关转发

**💡 知识点:**
- TTL=64且单跳到达，说明在同一网段
- ARP表显示网关(10.42.0.1)的MAC地址
- REACHABLE状态表示ARP缓存有效

---

### Step 9: 性能测试 (可选)
```bash
# 使用iperf3测试带宽
kubectl run iperf-server --image=networkstatic/iperf3 -- -s

# 等待启动
sleep 5

# 获取server IP
IPERF_IP=$(kubectl get pod iperf-server -o jsonpath='{.status.podIP}')

# 运行客户端测试
kubectl run iperf-client --image=networkstatic/iperf3 --rm -it -- -c $IPERF_IP -t 10
```

**预期输出:**
```
[ ID] Interval       Transfer     Bandwidth
[  5]  0.0-10.0 sec  10.2 GBytes  8.76 Gbits/sec
```

**验证点:** ✅ 了解Pod间网络性能

---

## ✅ 验证清单

实验完成后，确认以下要点：

- [ ] 找到并查看了CNI配置文件
- [ ] 理解CNI插件的作用
- [ ] 观察到veth pair的存在
- [ ] 理解veth pair的对应关系 (ifXX)
- [ ] 了解网桥或路由的转发机制
- [ ] 成功使用tcpdump抓包
- [ ] 追踪了数据包的转发路径
- [ ] 理解整个网络数据流

## 🔧 故障排查

### 问题1: 找不到CNI配置文件

**原因:** 路径不对或权限不足

**解决:**
```bash
# K3s的CNI配置通常在
sudo ls /var/lib/rancher/k3s/agent/etc/cni/net.d/

# 或
sudo find /etc -name "*cni*" -type d
```

---

### 问题2: tcpdump无法抓包

**原因:** 接口名称不对

**解决:**
```bash
# 列出所有接口
ip link show

# 找到相关接口 (cni0, flannel.1, veth等)
# 使用正确的接口名
sudo tcpdump -i <正确的接口名> -n
```

---

### 问题3: 无法查看容器PID

**原因:** K3s使用containerd，不是docker

**解决:**
```bash
# 使用crictl
sudo crictl ps | grep test-pod
sudo crictl inspect <container-id>

# 或直接查看Pod
kubectl get pod test-pod -o yaml | grep uid
```

---

## 🧪 扩展练习

### 1. 对比不同CNI插件
- 研究Flannel的VXLAN模式和host-gw模式
- 理解overlay和underlay网络的区别

### 2. 模拟网络故障
- 手动删除veth接口，观察Pod状态
- 修改路由表，观察连通性变化

### 3. 深入分析iptables规则
```bash
# 查看K3s创建的iptables规则
sudo iptables-save | grep cni
sudo iptables -t nat -L -n -v
```

---

## 📚 知识总结

### CNI工作流程

1. **Pod创建时**:
   - kubelet调用CNI插件
   - CNI创建veth pair
   - 一端放入Pod网络命名空间
   - 另一端连接到主机网桥或设置路由

2. **网络配置**:
   - 为Pod分配IP
   - 配置默认网关
   - 设置路由规则

3. **数据转发**:
   - Pod → veth → 网桥/路由 → veth → Pod
   - 或 Pod → veth → 路由 → 物理网卡 → 其他节点

### veth pair原理

- 虚拟以太网设备对
- 一端发送的数据包从另一端接收
- 用于连接不同网络命名空间
- 类似"网线"连接两个网卡

### Linux网桥作用

- 工作在数据链路层 (L2)
- 连接多个网络接口
- 类似物理交换机
- 转发以太网帧

### 数据包转发路径
```
Pod-A (10.42.0.20)
  ↓ eth0
  ↓ veth pair
  ↓ 主机veth接口
  ↓ 网桥 cni0 / 路由
  ↓ 主机veth接口
  ↓ veth pair
  ↓ eth0
Pod-B (10.42.0.21)
```

---

## 🧹 清理环境
```bash
# 删除测试Pod
kubectl delete pod test-pod test-pod-2 iperf-server --ignore-not-found=true

# 验证清理
kubectl get pod
```

**注意:** 实验3将创建Service，可以继续使用当前环境。

---

## 📖 参考资料

- [CNI规范详解](https://github.com/containernetworking/cni/blob/master/SPEC.md)
- [Linux veth设备](https://man7.org/linux/man-pages/man4/veth.4.html)
- [Linux bridge](https://wiki.linuxfoundation.org/networking/bridge)
- [Flannel网络插件](https://github.com/flannel-io/flannel)
- [K3s网络配置](https://docs.k3s.io/networking)

---

**实验2完成！** 🎉

继续下一个实验前，确保理解：
- CNI插件的工作流程
- veth pair如何连接Pod和主机
- 数据包在Pod间的转发路径
- 网桥或路由在转发中的作用

---
