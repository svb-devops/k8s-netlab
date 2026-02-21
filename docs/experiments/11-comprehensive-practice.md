# 实验11: 综合实战 — 部署完整三层Web应用

## 📋 实验信息

- **难度**: ⭐⭐⭐⭐ (中高级)
- **时长**: 50-60分钟
- **环境**: K3s单节点集群
- **前置**: 完成实验1-10（所有前置实验）

## 🎯 学习目标

通过本实验，你将：
1. 综合运用前10个实验的所有核心知识
2. 部署一个完整的三层Web应用（前端 + 后端API + 数据库）
3. 实践Namespace隔离、ConfigMap/Secret配置管理
4. 掌握多组件协作和服务间通信
5. 理解Ingress统一路由的实际配置
6. 掌握有状态组件（数据库）的生产级部署模式
7. 学习应用扩容、滚动更新、故障排查的完整流程

## 📚 前置知识

- 完成实验1-10（全部）
- 理解Pod、Deployment、Service、Ingress
- 理解ConfigMap、Secret、PV/PVC
- 理解StatefulSet和Headless Service
- 了解kubectl logs和故障排查流程

---

## 🐳 实验镜像说明

本实验使用的镜像：

### nginx
- **用途**: 前端静态页面服务器 + 反向代理
- **场景**: 前端层，同时作为API网关

### httpd (Apache)
- **用途**: 模拟后端API服务
- **场景**: 后端应用层（演示多层通信）

### redis
- **用途**: 模拟有状态数据存储
- **场景**: 数据层（用StatefulSet部署）

### busybox:1.28
- **用途**: 网络测试和服务验证
- **场景**: 验证各层间通信

**💡 综合实战特点:**
- 模拟真实生产应用的部署模式
- 所有组件独立Namespace隔离
- ConfigMap管理配置，Secret管理密钥
- 验证完整的请求链路

**📖 项目架构说明:**
```
用户请求
  ↓
Ingress（路由规则）
  ↓
前端Service → 前端Pod (nginx)
  ↓ /api 路由
后端Service → 后端Pod (httpd)
  ↓
数据库Service → 数据库Pod (redis, StatefulSet)

配置: ConfigMap (应用配置)
密钥: Secret (数据库密码)
存储: PVC (数据库持久化)
```

---

## ⚠️ 开始实验前

VM刚启动时，K3s需要约2-3分钟完成初始化。请先确认环境就绪：

```bash
# 等待节点Ready
kubectl wait --for=condition=Ready node --all --timeout=180s

# 确认系统Pod运行正常
kubectl get pod -n kube-system

# 确认StorageClass可用
kubectl get storageclass

# 确认Ingress Controller运行
kubectl get pod -n kube-system | grep traefik
```

**预期结果:**
- 节点Ready
- traefik Ingress Controller运行中
- local-path StorageClass存在

如果看到节点NotReady或大量Pod处于Pending，请等待2-3分钟再继续。

---

## 🚀 实验步骤

### Step 1: 创建命名空间和基础配置

**创建独立的命名空间隔离项目资源:**

```bash
# 创建项目命名空间
kubectl create namespace webapp

# 验证命名空间
kubectl get namespace webapp
```

**创建应用配置 (ConfigMap):**

```bash
cat > webapp-config.yaml <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: webapp-config
  namespace: webapp
data:
  APP_ENV: "production"
  APP_NAME: "K8s NetLab Demo"
  DB_HOST: "redis.webapp.svc.cluster.local"
  DB_PORT: "6379"
  API_PREFIX: "/api"
  LOG_LEVEL: "info"
EOF

kubectl apply -f webapp-config.yaml
kubectl get configmap webapp-config -n webapp
```

**创建敏感信息 (Secret):**

```bash
# 创建数据库密码Secret（base64编码）
kubectl create secret generic webapp-secret \
  --from-literal=DB_PASSWORD=SuperSecret123 \
  --from-literal=API_KEY=apikey-demo-2026 \
  -n webapp

# 验证Secret创建（不显示内容）
kubectl get secret webapp-secret -n webapp
kubectl describe secret webapp-secret -n webapp
```

**验证点:** ✅ Namespace、ConfigMap、Secret创建成功

**💡 知识点（综合实验8）:**
- Namespace隔离不同项目资源
- ConfigMap管理非敏感配置
- Secret管理敏感信息（密码、密钥）
- `--from-literal` 快速创建Secret
- 跨Namespace引用格式：`<service>.<namespace>.svc.cluster.local`

---

### Step 2: 部署数据库层（StatefulSet）

**创建数据库Headless Service:**

```bash
cat > db-service.yaml <<EOF
apiVersion: v1
kind: Service
metadata:
  name: redis
  namespace: webapp
  labels:
    app: redis
spec:
  clusterIP: None          # Headless Service
  selector:
    app: redis
  ports:
  - port: 6379
    name: redis
---
apiVersion: v1
kind: Service
metadata:
  name: redis-svc
  namespace: webapp
  labels:
    app: redis
spec:
  selector:
    app: redis
  ports:
  - port: 6379
    targetPort: 6379
EOF

kubectl apply -f db-service.yaml
kubectl get svc -n webapp
```

**创建数据库StatefulSet:**

```bash
cat > db-statefulset.yaml <<EOF
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: redis
  namespace: webapp
spec:
  serviceName: "redis"
  replicas: 1
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
      - name: redis
        image: redis
        ports:
        - containerPort: 6379
          name: redis
        env:
        - name: REDIS_PASSWORD
          valueFrom:
            secretKeyRef:
              name: webapp-secret
              key: DB_PASSWORD
        command: ["redis-server"]
        args: ["--requirepass", "\$(REDIS_PASSWORD)"]
        volumeMounts:
        - name: data
          mountPath: /data
        readinessProbe:
          exec:
            command: ["redis-cli", "ping"]
          initialDelaySeconds: 5
          periodSeconds: 5
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: "local-path"
      resources:
        requests:
          storage: 1Gi
EOF

kubectl apply -f db-statefulset.yaml

# 等待数据库就绪
kubectl wait --for=condition=Ready pod/redis-0 -n webapp --timeout=120s
echo "数据库已就绪"

# 验证数据库
kubectl get pod,pvc -n webapp
```

**测试数据库连通性:**

```bash
# 从数据库Pod内部测试
DB_PASS=$(kubectl get secret webapp-secret -n webapp \
  -o jsonpath='{.data.DB_PASSWORD}' | base64 -d)

kubectl exec redis-0 -n webapp -- redis-cli -a "$DB_PASS" ping
```

**预期输出:** `PONG`

**验证点:** ✅ 数据库StatefulSet运行，PVC绑定，连接验证通过

**💡 知识点（综合实验7+9）:**
- StatefulSet保证数据库Pod稳定标识
- PVC持久化数据库数据
- Secret注入敏感配置（密码）
- readinessProbe确保Pod真正就绪后才接收流量
- Headless Service用于StatefulSet DNS

---

### Step 3: 部署后端API层（Deployment）

```bash
cat > backend-deployment.yaml <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: backend
  namespace: webapp
spec:
  replicas: 2
  selector:
    matchLabels:
      app: backend
  template:
    metadata:
      labels:
        app: backend
    spec:
      containers:
      - name: api
        image: httpd
        ports:
        - containerPort: 80
        env:
        - name: APP_ENV
          valueFrom:
            configMapKeyRef:
              name: webapp-config
              key: APP_ENV
        - name: DB_HOST
          valueFrom:
            configMapKeyRef:
              name: webapp-config
              key: DB_HOST
        - name: DB_PASSWORD
          valueFrom:
            secretKeyRef:
              name: webapp-secret
              key: DB_PASSWORD
        resources:
          requests:
            memory: "64Mi"
            cpu: "50m"
          limits:
            memory: "128Mi"
            cpu: "100m"
---
apiVersion: v1
kind: Service
metadata:
  name: backend
  namespace: webapp
spec:
  selector:
    app: backend
  ports:
  - port: 80
    targetPort: 80
EOF

kubectl apply -f backend-deployment.yaml

# 等待后端就绪
kubectl wait --for=condition=Ready pod -l app=backend -n webapp --timeout=120s

# 查看后端状态
kubectl get pod,svc -n webapp -l app=backend
```

**验证后端API访问:**

```bash
# 从集群内部验证
kubectl run api-test --image=busybox:1.28 --rm -it \
  --restart=Never -n webapp -- \
  wget -q -O- http://backend.webapp.svc.cluster.local/
```

**预期输出:** 看到httpd的默认页面HTML

**验证后端环境变量注入:**

```bash
# 检查ConfigMap和Secret是否正确注入
kubectl exec -n webapp \
  $(kubectl get pod -n webapp -l app=backend -o jsonpath='{.items[0].metadata.name}') \
  -- env | grep -E "APP_ENV|DB_HOST|DB_PASSWORD"
```

**预期输出:**
```
APP_ENV=production
DB_HOST=redis.webapp.svc.cluster.local
DB_PASSWORD=SuperSecret123
```

**验证点:** ✅ 后端2副本运行，ConfigMap/Secret正确注入

**💡 知识点（综合实验3+8）:**
- Deployment管理无状态后端，支持水平扩展
- ConfigMap和Secret通过env注入配置
- Service提供稳定的ClusterIP给Ingress使用
- resources设置合理的资源限制

---

### Step 4: 部署前端层（Deployment）

**创建Nginx自定义配置（通过ConfigMap）:**

```bash
cat > frontend-config.yaml <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: nginx-config
  namespace: webapp
data:
  nginx.conf: |
    server {
        listen 80;
        server_name _;

        location / {
            root /usr/share/nginx/html;
            index index.html;
        }

        location /api/ {
            proxy_pass http://backend.webapp.svc.cluster.local/;
            proxy_set_header Host \$host;
            proxy_set_header X-Real-IP \$remote_addr;
        }
    }
  index.html: |
    <!DOCTYPE html>
    <html>
    <head><title>K8s NetLab Demo</title></head>
    <body>
      <h1>Welcome to K8s NetLab!</h1>
      <p>Kubernetes Comprehensive Practice</p>
      <p>Frontend: nginx | Backend: httpd | Database: redis</p>
    </body>
    </html>
EOF

kubectl apply -f frontend-config.yaml
```

**部署前端:**

```bash
cat > frontend-deployment.yaml <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: frontend
  namespace: webapp
spec:
  replicas: 2
  selector:
    matchLabels:
      app: frontend
  template:
    metadata:
      labels:
        app: frontend
    spec:
      containers:
      - name: nginx
        image: nginx
        ports:
        - containerPort: 80
        volumeMounts:
        - name: config
          mountPath: /etc/nginx/conf.d/default.conf
          subPath: nginx.conf
        - name: config
          mountPath: /usr/share/nginx/html/index.html
          subPath: index.html
        resources:
          requests:
            memory: "32Mi"
            cpu: "25m"
          limits:
            memory: "64Mi"
            cpu: "50m"
      volumes:
      - name: config
        configMap:
          name: nginx-config
---
apiVersion: v1
kind: Service
metadata:
  name: frontend
  namespace: webapp
spec:
  selector:
    app: frontend
  ports:
  - port: 80
    targetPort: 80
EOF

kubectl apply -f frontend-deployment.yaml

# 等待前端就绪
kubectl wait --for=condition=Ready pod -l app=frontend -n webapp --timeout=120s

# 验证前端
kubectl get pod,svc -n webapp -l app=frontend
```

**验证前端访问:**

```bash
kubectl run fe-test --image=busybox:1.28 --rm -it \
  --restart=Never -n webapp -- \
  wget -q -O- http://frontend.webapp.svc.cluster.local/
```

**预期输出:** 包含 "Welcome to K8s NetLab!" 的HTML

**验证点:** ✅ 前端2副本运行，ConfigMap挂载nginx配置，页面内容正确

**💡 知识点（综合实验4+8）:**
- ConfigMap以Volume方式挂载配置文件
- `subPath` 挂载单个文件而非整个目录
- Nginx反向代理 `/api/` 路径到后端Service
- Service DNS格式：`<name>.<namespace>.svc.cluster.local`

---

### Step 5: 配置Ingress路由

**创建Ingress统一对外暴露:**

```bash
# 获取节点IP（用于访问测试）
NODE_IP=$(kubectl get node -o jsonpath='{.items[0].status.addresses[0].address}')
echo "节点IP: $NODE_IP"

cat > ingress.yaml <<EOF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: webapp-ingress
  namespace: webapp
  annotations:
    traefik.ingress.kubernetes.io/router.entrypoints: web
spec:
  rules:
  - host: webapp.local
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: frontend
            port:
              number: 80
EOF

kubectl apply -f ingress.yaml

# 查看Ingress
kubectl get ingress -n webapp
kubectl describe ingress webapp-ingress -n webapp
```

**测试通过Ingress访问（使用节点IP+Host头）:**

```bash
NODE_IP=$(kubectl get node -o jsonpath='{.items[0].status.addresses[0].address}')

# 访问前端
curl -H "Host: webapp.local" http://$NODE_IP/ 2>/dev/null | grep -o "<h1>.*</h1>"

# 访问API路径（通过nginx proxy_pass转发到后端）
curl -H "Host: webapp.local" http://$NODE_IP/api/ 2>/dev/null | head -3
```

**预期输出:**
```
<h1>Welcome to K8s NetLab!</h1>
...httpd默认页面...
```

**验证点:** ✅ Ingress路由配置正确，流量统一进入nginx前端

**💡 知识点（综合实验4）:**
- Ingress统一对外入口，基于Host路由到前端nginx
- nginx内部通过 `proxy_pass` 将 `/api/` 转发到后端Service
- K3s内置Traefik作为Ingress Controller
- `pathType: Prefix` 前缀匹配
- 生产环境通过DNS将域名指向节点IP

---

### Step 6: 验证完整请求链路

**全链路验证脚本:**

```bash
NODE_IP=$(kubectl get node -o jsonpath='{.items[0].status.addresses[0].address}')
DB_PASS=$(kubectl get secret webapp-secret -n webapp \
  -o jsonpath='{.data.DB_PASSWORD}' | base64 -d)

echo "=========================================="
echo "  K8s NetLab 三层应用全链路验证"
echo "=========================================="

echo ""
echo "【1】命名空间资源总览"
kubectl get all -n webapp

echo ""
echo "【2】前端访问验证"
RESULT=$(curl -s -H "Host: webapp.local" http://$NODE_IP/ | grep -o "K8s NetLab")
if [ "$RESULT" = "K8s NetLab" ]; then
  echo "  ✅ 前端: 访问成功"
else
  echo "  ❌ 前端: 访问失败"
fi

echo ""
echo "【3】后端API验证"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: webapp.local" http://$NODE_IP/api/)
if [ "$STATUS" = "200" ]; then
  echo "  ✅ 后端API: HTTP $STATUS"
else
  echo "  ⚠️  后端API: HTTP $STATUS"
fi

echo ""
echo "【4】数据库验证"
DB_RESULT=$(kubectl exec redis-0 -n webapp -- redis-cli -a "$DB_PASS" ping 2>/dev/null)
if [ "$DB_RESULT" = "PONG" ]; then
  echo "  ✅ 数据库: $DB_RESULT"
else
  echo "  ❌ 数据库: 连接失败"
fi

echo ""
echo "【5】数据写入和读取测试"
kubectl exec redis-0 -n webapp -- redis-cli -a "$DB_PASS" \
  SET test_key "Hello from K8s!" 2>/dev/null
READ_RESULT=$(kubectl exec redis-0 -n webapp -- redis-cli -a "$DB_PASS" \
  GET test_key 2>/dev/null)
echo "  写入: test_key = Hello from K8s!"
echo "  读取: $READ_RESULT"
if [ "$READ_RESULT" = "Hello from K8s!" ]; then
  echo "  ✅ 数据读写: 正常"
fi

echo ""
echo "【6】资源使用情况"
kubectl top pods -n webapp 2>/dev/null || echo "  (metrics-server未就绪，跳过)"

echo ""
echo "=========================================="
echo "  全链路验证完成"
echo "=========================================="
```

**验证点:** ✅ 前端→后端→数据库完整链路验证通过

**💡 知识点（综合实验1-10）:**
- 完整三层架构在Kubernetes中的实现
- 各层通过Service DNS互相发现
- Ingress统一对外路由
- 数据在StatefulSet PVC中持久化

---

### Step 7: 运维操作演练

**7.1 扩容前端副本（应对流量增长）:**

```bash
# 扩容前端到4副本
kubectl scale deployment frontend -n webapp --replicas=4

# 观察扩容
kubectl get pod -n webapp -l app=frontend -w &
sleep 10
kill %1

kubectl get pod -n webapp -l app=frontend
```

**7.2 模拟故障：删除前端Pod，观察自愈:**

```bash
# 删除一个前端Pod
FE_POD=$(kubectl get pod -n webapp -l app=frontend -o jsonpath='{.items[0].metadata.name}')
echo "删除Pod: $FE_POD"
kubectl delete pod $FE_POD -n webapp

# 立即查看（Deployment会自动重建）
kubectl get pod -n webapp -l app=frontend
sleep 5
kubectl get pod -n webapp -l app=frontend
```

**7.3 滚动更新前端（模拟版本升级）:**

```bash
# 更新前端镜像版本
kubectl set image deployment/frontend nginx=nginx:1.25 -n webapp

# 观察滚动更新
kubectl rollout status deployment/frontend -n webapp

# 查看更新历史
kubectl rollout history deployment/frontend -n webapp
```

**7.4 查看应用日志（故障排查）:**

```bash
# 查看各层日志
echo "=== 前端日志 ==="
kubectl logs -l app=frontend -n webapp --tail=5 --prefix=true

echo "=== 后端日志 ==="
kubectl logs -l app=backend -n webapp --tail=5 --prefix=true

echo "=== 数据库日志 ==="
kubectl logs redis-0 -n webapp --tail=5
```

**7.5 验证数据库数据持久化（删除Pod后数据仍在）:**

```bash
# 当前数据
kubectl exec redis-0 -n webapp -- redis-cli \
  -a $(kubectl get secret webapp-secret -n webapp \
    -o jsonpath='{.data.DB_PASSWORD}' | base64 -d) \
  GET test_key 2>/dev/null

# 删除数据库Pod（StatefulSet会重建）
kubectl delete pod redis-0 -n webapp

# 等待重建
kubectl wait --for=condition=Ready pod/redis-0 -n webapp --timeout=120s

# 验证数据仍然存在
kubectl exec redis-0 -n webapp -- redis-cli \
  -a $(kubectl get secret webapp-secret -n webapp \
    -o jsonpath='{.data.DB_PASSWORD}' | base64 -d) \
  GET test_key 2>/dev/null
```

**预期输出（两次）:** `Hello from K8s!`

**验证点:** ✅ 扩容、自愈、滚动更新、日志查看、数据持久化全部通过

**💡 知识点（综合实验9+10）:**
- Deployment支持水平扩容，StatefulSet有序扩缩容
- Deployment自动维护副本数量，故障自愈
- 滚动更新保证零停机升级
- kubectl logs -l 按标签查看多Pod日志
- StatefulSet PVC在Pod重建后数据持久

---

## ✅ 验证清单

- [ ] 创建独立命名空间隔离项目
- [ ] ConfigMap管理应用配置
- [ ] Secret管理数据库密码
- [ ] 数据库StatefulSet运行，PVC持久化
- [ ] 后端API Deployment运行，配置正确注入
- [ ] 前端Deployment运行，Nginx反代配置正确
- [ ] Ingress路由前端和API路径
- [ ] 全链路访问验证通过
- [ ] 扩容前端副本
- [ ] 验证故障自愈
- [ ] 滚动更新前端
- [ ] 验证数据库数据持久化

---

## 🔧 故障排查

### 问题1: Pod无法启动（镜像拉取失败）

```bash
# 查看Pod状态
kubectl get pod -n webapp

# 查看事件
kubectl describe pod <pod-name> -n webapp | tail -20

# 检查镜像名是否正确
kubectl get pod <pod-name> -n webapp -o jsonpath='{.spec.containers[0].image}'
```

---

### 问题2: 服务无法访问（网络不通）

```bash
# 验证Service是否有Endpoints
kubectl get endpoints -n webapp

# 检查Pod标签是否与Service selector匹配
kubectl get pod -n webapp --show-labels

# 集群内部测试连通性
kubectl run net-test --image=busybox:1.28 --rm -it \
  --restart=Never -n webapp -- wget -q -O- http://backend/
```

---

### 问题3: Ingress访问404/502

```bash
# 检查Ingress配置
kubectl describe ingress webapp-ingress -n webapp

# 检查Ingress Controller是否运行
kubectl get pod -n kube-system | grep traefik

# 检查Service名称是否与Ingress配置一致
kubectl get svc -n webapp
```

---

### 问题4: 数据库连接失败

```bash
# 验证数据库Pod运行
kubectl get pod redis-0 -n webapp

# 验证Secret内容
kubectl get secret webapp-secret -n webapp \
  -o jsonpath='{.data.DB_PASSWORD}' | base64 -d

# 直接测试连接
kubectl exec redis-0 -n webapp -- redis-cli ping
```

---

### 问题5: ConfigMap修改后未生效

```bash
# 修改ConfigMap
kubectl edit configmap webapp-config -n webapp

# 重启相关Pod使配置生效（环境变量方式不会热更新）
kubectl rollout restart deployment/backend -n webapp
kubectl rollout restart deployment/frontend -n webapp
```

---

## 🧪 扩展练习

### 1. 添加Redis缓存（扩展数据层）

```yaml
# 在后端Deployment中添加缓存连接配置
env:
- name: CACHE_HOST
  valueFrom:
    configMapKeyRef:
      name: webapp-config
      key: DB_HOST
```

### 2. 配置应用健康检查

```yaml
livenessProbe:
  httpGet:
    path: /
    port: 80
  initialDelaySeconds: 10
  periodSeconds: 30

readinessProbe:
  httpGet:
    path: /
    port: 80
  initialDelaySeconds: 5
  periodSeconds: 10
```

### 3. 配置水平自动扩缩容 (HPA)

```bash
# 基于CPU使用率自动扩缩容
kubectl autoscale deployment frontend \
  -n webapp \
  --min=2 \
  --max=10 \
  --cpu-percent=70

kubectl get hpa -n webapp
```

### 4. 网络策略（限制访问）

```yaml
# 只允许前端访问后端
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: backend-policy
  namespace: webapp
spec:
  podSelector:
    matchLabels:
      app: backend
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: frontend
```

---

## 📖 知识总结

### 三层应用架构在Kubernetes中的实现

```
┌─────────────────────────────────────────────────────┐
│                  Namespace: webapp                   │
│                                                     │
│  Ingress (webapp.local)                             │
│    /  ──────────────→  frontend Service             │
│    /api ────────────→  backend Service              │
│                                                     │
│  frontend Deployment (nginx × 2)                   │
│    - ConfigMap挂载Nginx配置                          │
│    - 反向代理 /api → backend                        │
│                                                     │
│  backend Deployment (httpd × 2)                    │
│    - ConfigMap注入应用配置                           │
│    - Secret注入数据库密码                            │
│                                                     │
│  redis StatefulSet (redis × 1)                     │
│    - Headless Service提供DNS                        │
│    - PVC持久化数据                                   │
│    - Secret注入认证密码                              │
│                                                     │
│  ConfigMap: webapp-config, nginx-config             │
│  Secret: webapp-secret                              │
└─────────────────────────────────────────────────────┘
```

### 各实验知识汇总

| 实验 | 核心知识 | 在本项目中的应用 |
|------|---------|----------------|
| 实验1 | Pod网络基础 | 所有Pod间通信基础 |
| 实验2-3 | Service ClusterIP/NodePort | 各层Service定义 |
| 实验4 | Ingress路由 | 统一对外入口 |
| 实验5 | NetworkPolicy | 扩展练习安全隔离 |
| 实验6 | DNS服务发现 | 跨Namespace DNS访问 |
| 实验7 | 持久化存储PVC | 数据库数据持久化 |
| 实验8 | ConfigMap/Secret | 配置和密钥管理 |
| 实验9 | StatefulSet | 数据库有序部署 |
| 实验10 | 监控日志 | 故障排查和运维 |
| 实验11 | 综合实战 | 完整项目部署 |

### 生产环境最佳实践

1. **Namespace隔离** — 不同项目/环境使用独立Namespace
2. **资源限制** — 所有容器设置requests和limits
3. **健康检查** — 配置liveness和readiness探针
4. **配置分离** — 敏感信息用Secret，普通配置用ConfigMap
5. **有序部署** — 数据库先于应用启动（initContainers或脚本）
6. **持久化存储** — 有状态组件必须使用PVC
7. **服务发现** — 通过Service DNS互相访问
8. **日志规范** — 统一输出到stdout，由Kubernetes管理
9. **滚动更新** — 避免停机，配置合理的更新策略
10. **自动伸缩** — 使用HPA应对流量变化

---

## 🧹 清理环境

```bash
# 删除整个命名空间（清理所有资源）
kubectl delete namespace webapp

# 删除配置文件
rm -f webapp-config.yaml db-service.yaml db-statefulset.yaml \
      backend-deployment.yaml frontend-config.yaml \
      frontend-deployment.yaml ingress.yaml

# 验证清理完成
kubectl get namespace webapp 2>/dev/null && echo "仍存在" || echo "清理成功"
```

**注意:** 删除namespace会清理其中所有资源，包括PVC和PV（数据将丢失）。生产环境请先备份数据。

---

## 📎 参考资料

- [Kubernetes应用部署最佳实践](https://kubernetes.io/docs/concepts/workloads/)
- [Namespace隔离文档](https://kubernetes.io/docs/concepts/overview/working-with-objects/namespaces/)
- [生产级Kubernetes配置](https://kubernetes.io/docs/concepts/configuration/overview/)

---

**实验11完成！** 🎉

**恭喜你完成了全部11个实验！** 🏆

你已经掌握了：
- Pod网络和容器通信原理
- Service的各种类型和负载均衡
- Ingress路由和外部访问
- 网络策略和安全隔离
- DNS服务发现机制
- 持久化存储PV/PVC/StorageClass
- ConfigMap和Secret配置管理
- StatefulSet有状态应用管理
- 监控日志和故障排查
- **综合项目部署和运维实践**

**你已具备在Kubernetes上部署和管理生产级应用的能力！**
