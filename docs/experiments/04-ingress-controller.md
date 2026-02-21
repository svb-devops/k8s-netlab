# 实验4: Ingress控制器详解

## 📋 实验信息

- **难度**: ⭐⭐⭐⭐ (中高级)
- **时长**: 45-50分钟
- **环境**: K3s单节点集群（Traefik Ingress Controller）
- **前置**: 完成实验1-3，理解Service概念

## 🎯 学习目标

通过本实验，你将：
1. 理解Ingress的工作原理和应用场景
2. 掌握Ingress规则的配置方法
3. 学习基于路径的路由规则
4. 学习基于主机名的路由规则
5. 了解Ingress与Service的关系
6. 掌握Traefik的基本使用

## 📚 前置知识

- 完成实验3，理解Service概念
- 了解HTTP协议基础
- 理解域名和路径的概念
- 了解负载均衡基本原理

---

## 🐳 实验镜像说明

本实验使用的镜像：

### nginx
- **用途**: HTTP Web服务，演示Ingress路由
- **场景**: 创建多个不同的服务
- **版本**: latest（或指定稳定版本）

### httpd (可选)
- **用途**: 另一个Web服务，用于区分不同应用
- **场景**: 演示多服务路由

**💡 Ingress实验特点:**
- 需要多个不同的后端服务
- 通过HTTP请求验证路由规则
- 演示真实的微服务路由场景
- K3s自带Traefik，无需额外安装

**📖 关于Traefik:**
- K3s默认Ingress Controller
- 自动部署在kube-system命名空间
- 支持HTTP和HTTPS
- 配置简单，功能强大

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

### Step 1: 检查Traefik Ingress Controller

首先，让我们检查K3s自带的Traefik Ingress Controller状态：

```bash
# 查看Traefik Pod状态
kubectl get pod -n kube-system | grep traefik

# 查看Traefik Service
kubectl get svc -n kube-system | grep traefik

# 查看Traefik详细信息
kubectl describe deployment traefik -n kube-system
```

**预期输出:**
```
traefik-xxx-xxx   1/1   Running   ...
service/traefik   LoadBalancer   ...   80:xxxxx/TCP,443:xxxxx/TCP
```

**验证点:** ✅ Traefik运行正常，监听80和443端口

**💡 知识点:**
- Traefik是K3s默认的Ingress Controller
- 以Deployment形式部署在kube-system命名空间
- 通过LoadBalancer Service暴露（K3s使用ServiceLB）
- 自动监听HTTP(80)和HTTPS(443)端口

---

### Step 2: 创建第一个后端服务

创建第一个nginx服务作为后端：

```bash
# 创建nginx Deployment
kubectl create deployment web1 --image=nginx --replicas=2

# 等待Pod运行
kubectl wait --for=condition=Ready pod -l app=web1 --timeout=60s

# 等待容器完全启动
sleep 3

# 创建Service
kubectl expose deployment web1 --port=80 --name=web1-service

# 自定义web1的内容（便于区分）
kubectl exec -it deployment/web1 -- bash -c "echo 'This is Web Service 1' > /usr/share/nginx/html/index.html"

# 验证Service
kubectl get svc web1-service
```

**预期输出:**
```
NAME           TYPE        CLUSTER-IP      PORT(S)
web1-service   ClusterIP   10.43.x.x       80/TCP
```

**验证点:** ✅ web1-service创建成功，有ClusterIP

**💡 知识点:**
- 后端服务使用ClusterIP类型，不直接暴露
- 通过Ingress统一暴露多个服务
- 自定义内容便于验证路由效果

---

### Step 3: 创建第二个后端服务

创建第二个nginx服务，用于演示多服务路由：

```bash
# 创建第二个nginx Deployment
kubectl create deployment web2 --image=nginx --replicas=2

# 等待Pod运行
kubectl wait --for=condition=Ready pod -l app=web2 --timeout=60s

# 等待容器完全启动
sleep 3

# 创建Service
kubectl expose deployment web2 --port=80 --name=web2-service

# 自定义web2的内容
kubectl exec -it deployment/web2 -- bash -c "echo 'This is Web Service 2' > /usr/share/nginx/html/index.html"

# 验证两个Service
kubectl get svc
```

**预期输出:**
```
NAME            TYPE        CLUSTER-IP      PORT(S)
web1-service    ClusterIP   10.43.x.x       80/TCP
web2-service    ClusterIP   10.43.y.y       80/TCP
```

**验证点:** ✅ 两个后端服务都创建成功

**💡 知识点:**
- 微服务架构中通常有多个独立服务
- 每个服务有自己的ClusterIP
- Ingress作为统一入口管理路由

---

### Step 4: 创建基于主机名的Ingress规则

现在创建Ingress规则，实现基于主机名的路由（虚拟主机模式）：

```bash
cat > host-based-ingress.yaml <<EOF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: host-based-ingress
spec:
  rules:
  - host: web1.example.local
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: web1-service
            port:
              number: 80
  - host: web2.example.local
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: web2-service
            port:
              number: 80
EOF

# 应用Ingress规则
kubectl apply -f host-based-ingress.yaml

# 查看Ingress
kubectl get ingress

# 查看详细信息
kubectl describe ingress host-based-ingress
```

**预期输出:**
```
NAME                 CLASS    HOSTS                                    ADDRESS       PORTS   AGE
host-based-ingress   <none>   web1.example.local,web2.example.local   10.0.0.x      80      10s
```

**验证点:** ✅ Ingress创建成功，HOSTS显示两个域名

**💡 知识点:**
- `host` 字段定义虚拟主机名
- 通过HTTP Host header区分不同服务
- 同一IP可以托管多个域名
- `path: /` 表示该主机的所有路径
- Traefik根据请求的Host header路由到不同后端

---

### Step 5: 测试基于主机名的路由

测试Ingress路由是否正常工作：

```bash
# 获取Ingress的访问地址（Node IP）
NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
echo "Node IP: $NODE_IP"

# 使用Host header测试web1
curl -H "Host: web1.example.local" http://$NODE_IP/

# 使用Host header测试web2
curl -H "Host: web2.example.local" http://$NODE_IP/

# 不带Host header测试（应该404，因为没有匹配的host规则）
curl http://$NODE_IP/
```

**预期输出:**
```
# web1.example.local 返回:
This is Web Service 1

# web2.example.local 返回:
This is Web Service 2

# 无Host header 返回:
404 page not found
```

**验证点:** ✅ 主机名路由工作正常，不同Host访问不同服务

**💡 知识点:**
- Ingress根据HTTP Host header路由请求
- `Host: web1.example.local` 请求被路由到web1-service
- `Host: web2.example.local` 请求被路由到web2-service
- `-H "Host: xxx"` 参数设置HTTP请求头
- 未匹配的Host返回404
- 这是多租户SaaS应用的常用模式

---

### Step 6: 创建基于路径的Ingress规则（可选）

创建基于路径的Ingress，演示路径路由（适用于API版本控制场景）：

```bash
cat > path-based-ingress.yaml <<EOF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: path-based-ingress
  annotations:
    traefik.ingress.kubernetes.io/router.entrypoints: web
spec:
  rules:
  - http:
      paths:
      - path: /web1
        pathType: Prefix
        backend:
          service:
            name: web1-service
            port:
              number: 80
      - path: /web2
        pathType: Prefix
        backend:
          service:
            name: web2-service
            port:
              number: 80
EOF

# 应用Ingress规则
kubectl apply -f path-based-ingress.yaml

# 查看Ingress列表
kubectl get ingress
```

**测试基于路径的路由:**

```bash
# 测试访问web1（路径 /web1）
curl http://$NODE_IP/web1

# 测试访问web2（路径 /web2）
curl http://$NODE_IP/web2
```

**预期输出:**
```
# /web1 可能返回:
This is Web Service 1
# 或 404（取决于Traefik配置）

# /web2 可能返回:
This is Web Service 2
# 或 404（取决于Traefik配置）
```

**验证点:** ⚠️ 路径路由在某些配置下可能需要额外的路径重写注解

**💡 知识点:**
- `path: /web1` 定义路径前缀匹配
- `pathType: Prefix` 表示前缀匹配模式
- Traefik默认将完整路径转发到后端，可能需要路径重写
- 建议使用主机名路由（Step 4）作为首选方案
- 路径路由适合API版本控制（/api/v1, /api/v2）

---

### Step 7: 查看Ingress的工作原理

深入了解Ingress如何工作：

```bash
# 查看Ingress规则详情
kubectl describe ingress path-based-ingress

# 查看Traefik的配置（如果可以）
kubectl logs -n kube-system deployment/traefik --tail=50

# 查看Ingress的Events
kubectl get events --field-selector involvedObject.kind=Ingress
```

**分析Ingress配置:**

查看Ingress对象的详细信息，理解：
- **Rules**: 路由规则列表
- **Backend**: 后端服务配置
- **Events**: 配置更新事件

**💡 知识点:**
- Ingress Controller监听Ingress对象变化
- 自动更新路由配置
- 将配置转换为实际的负载均衡规则
- Traefik使用动态配置，无需重启

---

### Step 8: 测试Ingress的负载均衡

验证Ingress是否提供负载均衡：

```bash
# 多次请求测试负载均衡
for i in {1..10}; do
  echo "Request $i:"
  curl -s http://$NODE_IP/web1
  echo ""
done

# 查看web1的Pod
kubectl get pod -l app=web1 -o wide

# 查看具体哪个Pod处理了请求（查看日志）
kubectl logs -l app=web1 --tail=5
```

**验证点:** ✅ 请求被分发到不同的Pod

**💡 知识点:**
- Ingress → Service → Pod 完整链路
- Service提供负载均衡
- Ingress提供路由和入口管理
- 两层负载均衡保证高可用

---

### Step 9: 理解Ingress的路由优先级

测试不同路由规则的优先级：

```bash
# 创建更复杂的路由规则
cat > complex-ingress.yaml <<EOF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: complex-ingress
spec:
  rules:
  - http:
      paths:
      - path: /web1/api
        pathType: Prefix
        backend:
          service:
            name: web1-service
            port:
              number: 80
      - path: /web1
        pathType: Prefix
        backend:
          service:
            name: web2-service
            port:
              number: 80
EOF

# 应用配置
kubectl apply -f complex-ingress.yaml

# 测试不同路径
curl http://$NODE_IP/web1/api
curl http://$NODE_IP/web1
```

**💡 知识点:**
- 更具体的路径规则优先级更高
- `/web1/api` 比 `/web1` 更具体
- Ingress Controller自动处理优先级
- 规则顺序在某些Controller中很重要

---

### Step 10: 查看完整的流量路径

理解从客户端到Pod的完整流量路径：

```bash
# 查看完整的网络链路
echo "=== Ingress ==="
kubectl get ingress -o wide

echo -e "\n=== Services ==="
kubectl get svc -o wide

echo -e "\n=== Endpoints ==="
kubectl get endpoints

echo -e "\n=== Pods ==="
kubectl get pod -o wide

# 追踪一个请求的路径
echo -e "\n=== Testing Request Flow ==="
curl -v http://$NODE_IP/web1 2>&1 | grep -E "Host:|Connected to"
```

**流量路径分析:**
```
客户端请求 (curl)
  ↓
Node IP:80 (主机网络)
  ↓
Traefik Ingress Controller (Pod)
  ↓
解析Ingress规则 (匹配路径)
  ↓
Service (web1-service, ClusterIP)
  ↓
Endpoint (Pod IP列表)
  ↓
Pod (nginx容器)
```

**💡 知识点:**
- 完整的请求经过多层转发
- 每一层都有负载均衡和故障转移
- Service通过Endpoint跟踪Pod
- Ingress提供L7(应用层)路由

---

## ✅ 验证清单

实验完成后，确认以下要点：

- [ ] Traefik Ingress Controller运行正常
- [ ] 创建了两个后端Service（web1-service, web2-service）
- [ ] 基于路径的Ingress规则工作正常
- [ ] /web1 路由到 web1-service
- [ ] /web2 路由到 web2-service
- [ ] （可选）基于主机名的路由工作
- [ ] 理解Ingress的工作原理
- [ ] 理解Ingress与Service的关系
- [ ] 能够查看和分析Ingress配置
- [ ] 理解完整的流量路径

---

## 🔧 故障排查

### 问题1: Ingress无法访问

**原因:** Traefik服务未启动或端口未暴露

**解决:**
```bash
# 检查Traefik状态
kubectl get pod -n kube-system -l app.kubernetes.io/name=traefik

# 检查Service
kubectl get svc -n kube-system traefik

# 查看日志
kubectl logs -n kube-system -l app.kubernetes.io/name=traefik

# 如果Traefik未运行，检查K3s状态
systemctl status k3s
```

---

### 问题2: 404 Not Found

**原因:** Ingress规则未生效或路径不匹配

**解决:**
```bash
# 检查Ingress状态
kubectl describe ingress path-based-ingress

# 确认Rules和Backend配置
kubectl get ingress path-based-ingress -o yaml

# 检查Service是否存在
kubectl get svc

# 验证路径是否正确
# 确保请求路径与Ingress规则中的path匹配
```

---

### 问题3: 后端服务无响应

**原因:** Service或Pod有问题

**解决:**
```bash
# 检查Service的Endpoint
kubectl get endpoints web1-service

# 检查Pod状态
kubectl get pod -l app=web1

# 测试Service直接访问
kubectl run test --image=busybox:1.28 --rm -it -- wget -qO- http://web1-service

# 查看Pod日志
kubectl logs -l app=web1
```

---

### 问题4: Ingress规则冲突

**原因:** 多个Ingress规则匹配同一路径

**解决:**
```bash
# 查看所有Ingress规则
kubectl get ingress

# 查看详细配置
kubectl get ingress -o yaml

# 删除冲突的规则
kubectl delete ingress <conflicting-ingress-name>

# 重新应用正确的规则
kubectl apply -f path-based-ingress.yaml
```

---

### 问题5: 自定义内容未生效

**原因:** Pod未更新或命令执行失败

**解决:**
```bash
# 重新设置内容
kubectl exec -it deployment/web1 -- bash -c "echo 'This is Web Service 1' > /usr/share/nginx/html/index.html"

# 如果上述命令失败，直接进入Pod
kubectl exec -it deployment/web1 -- bash
# 然后手动执行：
echo 'This is Web Service 1' > /usr/share/nginx/html/index.html
exit

# 验证内容
kubectl exec deployment/web1 -- cat /usr/share/nginx/html/index.html
```

---

## 🧪 扩展练习

### 1. 默认后端配置

创建一个默认后端，处理未匹配的请求：

```bash
# 创建默认服务
kubectl create deployment default-backend --image=nginx
kubectl expose deployment default-backend --port=80 --name=default-service

# 自定义默认页面
kubectl exec -it deployment/default-backend -- bash -c "echo 'Default Backend - 404' > /usr/share/nginx/html/index.html"

# 更新Ingress添加默认后端
cat > ingress-with-default.yaml <<EOF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: ingress-with-default
spec:
  defaultBackend:
    service:
      name: default-service
      port:
        number: 80
  rules:
  - http:
      paths:
      - path: /web1
        pathType: Prefix
        backend:
          service:
            name: web1-service
            port:
              number: 80
EOF

kubectl apply -f ingress-with-default.yaml

# 测试未匹配路径
curl http://$NODE_IP/unknown-path
```

---

### 2. 路径重写

使用注解实现路径重写：

```bash
cat > rewrite-ingress.yaml <<EOF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: rewrite-ingress
  annotations:
    traefik.ingress.kubernetes.io/rewrite-target: /
spec:
  rules:
  - http:
      paths:
      - path: /app1
        pathType: Prefix
        backend:
          service:
            name: web1-service
            port:
              number: 80
EOF

kubectl apply -f rewrite-ingress.yaml

# 测试：/app1 会被重写为 / 然后转发到后端
curl http://$NODE_IP/app1
```

**说明:** 路径重写允许前端URL与后端路径不同

---

### 3. HTTPS配置（高级）

配置TLS/HTTPS支持：

```bash
# 创建自签名证书
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout tls.key -out tls.crt \
  -subj "/CN=web1.example.local/O=K8s Lab"

# 创建Secret
kubectl create secret tls tls-secret --key=tls.key --cert=tls.crt

# 在Ingress中配置TLS
cat > tls-ingress.yaml <<EOF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: tls-ingress
spec:
  tls:
  - hosts:
    - web1.example.local
    secretName: tls-secret
  rules:
  - host: web1.example.local
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: web1-service
            port:
              number: 80
EOF

kubectl apply -f tls-ingress.yaml

# 测试HTTPS访问
curl -k -H "Host: web1.example.local" https://$NODE_IP/
```

**注意:** `-k` 参数跳过证书验证（因为是自签名证书）

---

### 4. 多路径规则组合

创建复杂的路径路由规则：

```bash
cat > multi-path-ingress.yaml <<EOF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: multi-path-ingress
spec:
  rules:
  - http:
      paths:
      - path: /api/v1
        pathType: Prefix
        backend:
          service:
            name: web1-service
            port:
              number: 80
      - path: /api/v2
        pathType: Prefix
        backend:
          service:
            name: web2-service
            port:
              number: 80
      - path: /admin
        pathType: Prefix
        backend:
          service:
            name: web1-service
            port:
              number: 80
EOF

kubectl apply -f multi-path-ingress.yaml

# 测试不同API版本
curl http://$NODE_IP/api/v1
curl http://$NODE_IP/api/v2
curl http://$NODE_IP/admin
```

---

## 📖 知识总结

### Ingress工作原理

```
客户端请求
  ↓
Ingress Controller (Traefik)
  - 解析HTTP请求
  - 匹配Ingress规则
  - 选择后端Service
  ↓
Service (ClusterIP)
  - 负载均衡
  - 选择健康的Pod
  ↓
Pod (应用容器)
```

---

### Ingress vs Service

**Service:**
- 四层（TCP/UDP）负载均衡
- 集群内部访问
- 每个Service一个IP
- 支持多种类型：ClusterIP、NodePort、LoadBalancer

**Ingress:**
- 七层（HTTP/HTTPS）路由
- 统一外部入口
- 一个IP多个服务
- 支持路径路由、主机名路由
- 支持TLS/SSL
- 更灵活的流量管理

---

### Ingress Controller类型

不同的Ingress Controller实现：

- **Traefik**: K3s默认，配置简单，云原生
- **Nginx Ingress**: 最流行，功能强大，生产就绪
- **HAProxy**: 高性能，传统负载均衡器
- **Istio Gateway**: 服务网格方案，功能最全
- **Contour**: 基于Envoy，高性能
- **Ambassador**: API网关，适合微服务

---

### pathType 类型说明

Kubernetes支持三种pathType：

1. **Prefix**: 前缀匹配（最常用）
   - `/web1` 匹配 `/web1`、`/web1/`、`/web1/page` 等

2. **Exact**: 精确匹配
   - `/web1` 只匹配 `/web1`

3. **ImplementationSpecific**: 由Ingress Controller决定
   - 依赖具体实现

---

### 最佳实践

1. **使用ClusterIP Service作为后端**
   - Ingress管理外部访问
   - Service管理内部负载均衡
   - 职责分离，架构清晰

2. **合理设计路由规则**
   - 路径路由: API版本管理（/api/v1, /api/v2）
   - 主机名路由: 多租户场景（tenant1.app.com, tenant2.app.com）
   - 混合使用: 复杂业务场景

3. **配置健康检查**
   - 确保路由到健康的Pod
   - 自动剔除故障实例
   - 提高服务可用性

4. **TLS最佳实践**
   - 使用证书管理工具（cert-manager）
   - 自动更新证书
   - 强制HTTPS重定向
   - 使用有效的CA证书

5. **性能优化**
   - 启用连接保持（keep-alive）
   - 配置适当的超时时间
   - 使用缓存减少后端压力
   - 监控Ingress Controller性能

---

### 实际应用场景

**场景1: 微服务API网关**
```
/api/users    → user-service
/api/orders   → order-service
/api/products → product-service
```

**场景2: 多租户SaaS应用**
```
tenant1.app.com → tenant1-service
tenant2.app.com → tenant2-service
```

**场景3: 灰度发布/A/B测试**
```
通过权重或header路由到不同版本
v1.app.com → app-v1
v2.app.com → app-v2
```

---

## 🧹 清理环境

实验结束后，清理创建的资源：

```bash
# 删除Ingress规则
kubectl delete ingress host-based-ingress

# 删除可选的Ingress（如果创建了）
kubectl delete ingress path-based-ingress complex-ingress ingress-with-default rewrite-ingress tls-ingress multi-path-ingress 2>/dev/null || true

# 删除Service
kubectl delete svc web1-service web2-service

# 删除扩展练习的Service（如果创建了）
kubectl delete svc default-service 2>/dev/null || true

# 删除Deployment
kubectl delete deployment web1 web2

# 删除扩展练习的Deployment（如果创建了）
kubectl delete deployment default-backend 2>/dev/null || true

# 删除配置文件
rm -f host-based-ingress.yaml path-based-ingress.yaml complex-ingress.yaml
rm -f ingress-with-default.yaml rewrite-ingress.yaml tls-ingress.yaml multi-path-ingress.yaml
rm -f tls.key tls.crt 2>/dev/null || true

# 删除Secret（如果创建了）
kubectl delete secret tls-secret 2>/dev/null || true

# 验证清理
kubectl get ingress,svc,deployment
```

**预期输出:**
```
No resources found in default namespace.
```

**注意:** Traefik Ingress Controller是K3s系统组件，不要删除。

---

## 📚 参考资料

- [Kubernetes Ingress官方文档](https://kubernetes.io/docs/concepts/services-networking/ingress/)
- [Traefik文档](https://doc.traefik.io/traefik/)
- [K3s Networking](https://docs.k3s.io/networking)
- [Ingress控制器对比](https://kubernetes.io/docs/concepts/services-networking/ingress-controllers/)
- [Nginx Ingress Controller](https://kubernetes.github.io/ingress-nginx/)

---

**实验4完成！** 🎉

继续下一个实验前，确保理解：
- Ingress的工作原理和应用场景
- 如何配置基于路径和主机名的路由
- Ingress与Service的关系和区别
- Traefik的基本使用方法
- 完整的流量路径：客户端 → Ingress → Service → Pod
- 不同Ingress Controller的特点和选择

**下一步建议:**
- 实验5可能涉及：持久化存储（PV/PVC）
- 或者：ConfigMap和Secret配置管理
- 或者：有状态应用（StatefulSet）

祝你学习愉快！🚀
