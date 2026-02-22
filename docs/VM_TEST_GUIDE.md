# K8S NetLab VM 验证指南

本文档用于验证创建的VM和K3s集群状态，并测试实验文档的可执行性。

---

## 📋 前置条件

- ✅ K8S NetLab后端服务已启动
- ⏳ 用户通过Web界面创建VM
- ⏳ 获取VM的IP地址

---

## 🔌 Step 1: 连接到VM

### 方式A: 通过Web终端（推荐）

1. 访问 http://<your-server-ip>:8000
2. 登录账号
3. 在VM列表中找到你的VM
4. 点击 **"终端"** 按钮
5. 直接在浏览器中使用SSH终端

### 方式B: 通过SSH客户端

如果你知道VM的IP地址（从Web界面查看）：

```bash
# 替换 <VM_IP> 为实际IP地址
ssh k8s_lab@<VM_IP>

# 默认密码（首次登录后建议修改，在 .env 中配置 VM_SSH_PASSWORD）
# Password: <configured in .env as VM_SSH_PASSWORD>
```

**示例**:
```bash
# 替换 <vm-ip> 为从Web界面获取的实际IP
ssh k8s_lab@<vm-ip>
```

---

## ✅ Step 2: 验证K3s集群状态

### 2.1 检查K3s版本和状态

```bash
# 检查kubectl版本
kubectl version --short

# 或使用完整版本信息
kubectl version
```

**预期输出**:
```
Client Version: v1.28.x
Kustomize Version: v5.0.x
Server Version: v1.28.x
```

---

### 2.2 查看集群节点

```bash
# 查看节点状态
kubectl get nodes

# 查看详细信息
kubectl get nodes -o wide
```

**预期输出**:
```
NAME        STATUS   ROLES                  AGE   VERSION
k3s-node    Ready    control-plane,master   Xm    v1.28.x
```

**验证点**: ✅ 节点状态为 `Ready`

---

### 2.3 查看系统Pod

```bash
# 查看所有命名空间的Pod
kubectl get pod -A

# 或者查看kube-system命名空间
kubectl get pod -n kube-system
```

**预期输出**:
```
NAMESPACE     NAME                                     READY   STATUS    RESTARTS   AGE
kube-system   coredns-xxx                              1/1     Running   0          Xm
kube-system   local-path-provisioner-xxx               1/1     Running   0          Xm
kube-system   metrics-server-xxx                       1/1     Running   0          Xm
kube-system   svclb-traefik-xxx                        2/2     Running   0          Xm
kube-system   traefik-xxx                              1/1     Running   0          Xm
```

**验证点**: ✅ 所有系统Pod状态为 `Running`

---

### 2.4 检查K3s服务

```bash
# 查看K3s服务状态
systemctl status k3s --no-pager

# 或者只看运行状态
systemctl is-active k3s
```

**预期输出**:
```
● k3s.service - Lightweight Kubernetes
     Loaded: loaded
     Active: active (running) since ...
```

**验证点**: ✅ K3s服务状态为 `active (running)`

---

### 2.5 查看K3s配置文件

```bash
# 查看K3s配置目录
ls -la /etc/rancher/k3s/

# 查看K3s配置文件（如果存在）
cat /etc/rancher/k3s/config.yaml 2>/dev/null || echo "No custom config"

# 查看kubeconfig
ls -la /etc/rancher/k3s/k3s.yaml
```

**预期输出**:
```
total XX
drwxr-xr-x 2 root root  ...  .
drwxr-xr-x 3 root root  ...  ..
-rw------- 1 root root  ...  k3s.yaml
```

---

### 2.6 验证CNI插件配置

```bash
# 查看CNI配置目录
ls -la /var/lib/rancher/k3s/agent/etc/cni/net.d/

# 查看CNI配置内容
cat /var/lib/rancher/k3s/agent/etc/cni/net.d/*.conflist 2>/dev/null | head -20

# 查看CNI插件二进制
ls -la /var/lib/rancher/k3s/data/current/bin/
```

**预期输出**:
```
10-flannel.conflist

{
  "name": "cbr0",
  "cniVersion": "0.3.1",
  "plugins": [
    {
      "type": "flannel",
      ...
    }
  ]
}
```

**验证点**: ✅ 找到CNI配置文件（通常是Flannel）

---

## 🧪 Step 3: 测试实验1的基础功能

### 3.1 创建第一个测试Pod

```bash
# 创建nginx Pod（实验1 Step 1）
kubectl run nginx-1 --image=nginx

# 等待Pod就绪
kubectl wait --for=condition=Ready pod/nginx-1 --timeout=60s

# 查看Pod状态
kubectl get pod nginx-1 -o wide
```

**预期输出**:
```
NAME      READY   STATUS    RESTARTS   AGE   IP           NODE
nginx-1   1/1     Running   0          10s   10.42.0.X    k3s-node
```

**验证点**:
- ✅ Pod状态为 `Running`
- ✅ Pod获得IP地址（10.42.x.x 网段）

---

### 3.2 创建第二个测试Pod

```bash
# 创建第二个Pod（实验1 Step 2）
kubectl run nginx-2 --image=nginx

# 等待就绪
kubectl wait --for=condition=Ready pod/nginx-2 --timeout=60s

# 查看两个Pod
kubectl get pod -o wide
```

**预期输出**:
```
NAME      READY   STATUS    IP
nginx-1   1/1     Running   10.42.0.15
nginx-2   1/1     Running   10.42.0.16
```

**验证点**: ✅ 两个Pod都有独立IP

---

### 3.3 测试Pod间通信

```bash
# 获取nginx-2的IP（实验1 Step 3）
NGINX2_IP=$(kubectl get pod nginx-2 -o jsonpath='{.status.podIP}')
echo "nginx-2 IP: $NGINX2_IP"

# 从nginx-1 ping nginx-2
kubectl exec nginx-1 -- ping -c 3 $NGINX2_IP
```

**预期输出**:
```
PING 10.42.0.16 (10.42.0.16): 56 data bytes
64 bytes from 10.42.0.16: seq=0 ttl=64 time=0.089 ms
64 bytes from 10.42.0.16: seq=1 ttl=64 time=0.052 ms
64 bytes from 10.42.0.16: seq=2 ttl=64 time=0.048 ms

--- 10.42.0.16 ping statistics ---
3 packets transmitted, 3 packets received, 0% packet loss
```

**验证点**: ✅ Pod之间可以直接通信

---

### 3.4 测试Node到Pod的通信

```bash
# 获取Pod IP（实验1 Step 4）
POD_IP=$(kubectl get pod nginx-1 -o jsonpath='{.status.podIP}')
echo "nginx-1 IP: $POD_IP"

# 从Node直接访问Pod
curl -s http://$POD_IP | grep title
```

**预期输出**:
```
<title>Welcome to nginx!</title>
```

**验证点**: ✅ Node可以访问Pod IP

---

### 3.5 查看Pod网络接口

```bash
# 查看Pod内的网络配置（实验1 Step 5）
kubectl exec nginx-1 -- ip addr show

# 查看Pod的路由表
kubectl exec nginx-1 -- ip route
```

**预期输出**:
```
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536
    inet 127.0.0.1/8 scope host lo
3: eth0@if10: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1450
    inet 10.42.0.15/24 brd 10.42.0.255 scope global eth0

default via 10.42.0.1 dev eth0
10.42.0.0/24 dev eth0 proto kernel scope link src 10.42.0.15
```

**验证点**: ✅ Pod有独立的eth0接口和路由

---

### 3.6 测试外网连通性

```bash
# 测试Pod到外网（实验1 Step 6）
kubectl exec nginx-1 -- ping -c 3 8.8.8.8

# 测试DNS解析
kubectl exec nginx-1 -- nslookup kubernetes.default
```

**预期输出**:
```
PING 8.8.8.8 (8.8.8.8): 56 data bytes
64 bytes from 8.8.8.8: seq=0 ttl=115 time=10.2 ms
...

Server:    10.43.0.10
Address 1: 10.43.0.10 kube-dns.kube-system.svc.cluster.local
```

**验证点**: ✅ Pod可以访问外网和DNS

---

## 🧹 清理测试资源

```bash
# 删除测试Pod
kubectl delete pod nginx-1 nginx-2

# 验证清理完成
kubectl get pod
```

**预期输出**:
```
No resources found in default namespace.
```

---

## ✅ 完整验证清单

### K3s集群验证
- [ ] kubectl命令可用
- [ ] 节点状态为Ready
- [ ] 系统Pod全部Running
- [ ] K3s服务运行正常
- [ ] CNI插件配置存在

### 实验1基础功能验证
- [ ] 可以创建Pod
- [ ] Pod获得IP地址
- [ ] Pod之间可以通信
- [ ] Node可以访问Pod
- [ ] Pod有独立网络接口
- [ ] Pod可以访问外网
- [ ] DNS解析正常

---

## 🎯 下一步

如果所有验证都通过：

### 继续完整测试实验1
```bash
# 打开实验文档
cat /root/k8s-netlab/docs/experiments/01-kubernetes-network-basics.md

# 或在浏览器查看
# https://github.com/your-repo/k8s-netlab/blob/main/docs/experiments/01-kubernetes-network-basics.md
```

### 测试实验2和3
- 实验2: Pod网络实现原理深入探索
- 实验3: Service负载均衡机制

---

## 🐛 常见问题排查

### 问题1: kubectl命令找不到

**解决**:
```bash
# 检查kubeconfig
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

# 或创建软链接
ln -s /usr/local/bin/k3s /usr/local/bin/kubectl
```

### 问题2: Pod一直Pending

**解决**:
```bash
# 查看Pod详情
kubectl describe pod nginx-1

# 查看节点资源
kubectl describe node

# 查看事件
kubectl get events --sort-by=.metadata.creationTimestamp
```

### 问题3: 镜像拉取失败

**解决**:
```bash
# 检查网络
ping 8.8.8.8

# 查看containerd状态
systemctl status containerd

# 手动拉取镜像
crictl pull nginx:latest
```

---

## 📊 测试报告模板

完成测试后，记录结果：

```
【K8S NetLab 实验验证报告】

测试时间: YYYY-MM-DD HH:MM
VM ID: XXX
VM IP: 172.16.100.XXX

## K3s集群状态
- kubectl版本: v1.28.x ✅
- 节点状态: Ready ✅
- 系统Pod: 5/5 Running ✅
- CNI插件: Flannel ✅

## 实验1基础测试
- Step 1: 创建Pod ✅
- Step 2: 第二个Pod ✅
- Step 3: Pod间通信 ✅
- Step 4: Node到Pod ✅
- Step 5: 网络接口 ✅
- Step 6: 外网连通 ✅

## 问题记录
[如有问题记录在此]

## 总体评价
实验文档准确性: ⭐⭐⭐⭐⭐
命令可执行性: ⭐⭐⭐⭐⭐
```

---

**准备就绪！等待用户创建VM并开始测试。** 🚀
