# 实验8: ConfigMap和Secret配置管理

## 📋 实验信息

- **难度**: ⭐⭐⭐ (中级)
- **时长**: 35-40分钟
- **环境**: K3s单节点集群
- **前置**: 完成实验1-3，理解Pod基础

## 🎯 学习目标

通过本实验，你将：
1. 理解配置与代码分离的12要素应用原则
2. 掌握ConfigMap的创建方法（命令行/YAML）
3. 学习Secret的安全管理和Base64编码
4. 掌握环境变量注入方式
5. 学习Volume挂载方式
6. 理解配置更新和热更新机制
7. 掌握最佳安全实践

## 📚 前置知识

- 完成实验1-3，理解Pod基础
- 了解环境变量概念
- 理解文件系统基础
- 了解配置管理需求

---

## 🐳 实验镜像说明

本实验使用的镜像：

### busybox:1.28
- **用途**: 配置验证和测试
- **工具**: env, cat, sh等
- **场景**: 验证环境变量和文件内容

### nginx
- **用途**: Web应用配置场景
- **场景**: 配置文件挂载示例

**💡 配置管理实验特点:**
- 演示配置与代码分离
- 区分敏感和非敏感信息
- 学习两种注入方式
- 理解配置更新机制

**📖 关于Secret:**
- Base64编码存储（不是加密）
- etcd中加密存储（可选）
- 传输过程加密
- describe不显示内容（安全）

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

### Step 1: 使用命令行创建ConfigMap

**开始前快速检查:**

```bash
# 确认环境就绪（如果刚启动VM）
kubectl get nodes
# 应该显示: Ready

kubectl version --short
# 应该正常返回版本信息
```

如果命令超时或失败，请等待2-3分钟后重试。

**创建ConfigMap:**

```bash
# 方式1: 从字面值创建
kubectl create configmap app-config \
  --from-literal=APP_NAME=MyApp \
  --from-literal=APP_VERSION=1.0 \
  --from-literal=LOG_LEVEL=info

# 查看ConfigMap列表
kubectl get configmap
kubectl get cm

# 查看ConfigMap详情
kubectl describe configmap app-config

# 以YAML格式查看
kubectl get configmap app-config -o yaml
```

**预期输出:**
```yaml
data:
  APP_NAME: MyApp
  APP_VERSION: "1.0"
  LOG_LEVEL: info
```

**验证点:** ✅ ConfigMap创建成功，包含3个键值对

**💡 知识点:**
- ConfigMap存储非敏感配置
- 键值对形式存储
- --from-literal: 直接指定键值
- 可以包含多个配置项
- 与代码分离，便于不同环境复用

---

### Step 2: 从配置文件创建ConfigMap

```bash
# 创建配置文件
cat > app.properties <<EOF
database.host=mysql.default.svc.cluster.local
database.port=3306
database.name=myapp
cache.enabled=true
cache.ttl=300
EOF

# 从文件创建ConfigMap
kubectl create configmap app-properties --from-file=app.properties

# 查看ConfigMap内容
kubectl get configmap app-properties -o yaml

# 创建多文件ConfigMap
echo "server.port=8080" > server.conf
kubectl create configmap app-files \
  --from-file=app.properties \
  --from-file=server.conf

# 查看多文件ConfigMap
kubectl describe configmap app-files
```

**预期输出:**
```yaml
data:
  app.properties: |
    database.host=mysql.default.svc.cluster.local
    database.port=3306
    database.name=myapp
    cache.enabled=true
    cache.ttl=300
  server.conf: |
    server.port=8080
```

**验证点:** ✅ 从文件创建ConfigMap，文件内容成为data

**💡 知识点:**
- --from-file: 从文件创建
- 文件名成为key
- 文件内容成为value
- 可以包含多个文件
- 适合挂载配置文件的场景

---

### Step 3: 将ConfigMap作为环境变量注入

创建Pod配置文件：

```bash
cat > pod-with-cm-env.yaml <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: test-cm-env
spec:
  containers:
  - name: test-container
    image: busybox:1.28
    command: ["sh", "-c", "sleep 3600"]
    env:
    - name: APP_NAME
      valueFrom:
        configMapKeyRef:
          name: app-config
          key: APP_NAME
    - name: APP_VERSION
      valueFrom:
        configMapKeyRef:
          name: app-config
          key: APP_VERSION
    envFrom:
    - configMapRef:
        name: app-config
        prefix: CONFIG_
EOF

# 应用Pod
kubectl apply -f pod-with-cm-env.yaml

# 等待Pod运行
kubectl wait --for=condition=Ready pod/test-cm-env --timeout=60s

# 查看注入的环境变量
kubectl exec test-cm-env -- env | grep -E "APP_|CONFIG_"
```

**预期输出:**
```
APP_NAME=MyApp
APP_VERSION=1.0
CONFIG_APP_NAME=MyApp
CONFIG_APP_VERSION=1.0
CONFIG_LOG_LEVEL=info
```

**验证点:** ✅ ConfigMap成功注入为环境变量

**💡 知识点:**
- env.valueFrom: 单个键注入
- envFrom: 所有键注入
- prefix: 添加前缀避免冲突
- 环境变量在Pod创建时固定
- 更新ConfigMap后需重建Pod才能生效

---

### Step 4: 将ConfigMap挂载为文件

```bash
cat > pod-with-cm-volume.yaml <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: test-cm-volume
spec:
  containers:
  - name: test-container
    image: busybox:1.28
    command: ["sh", "-c", "sleep 3600"]
    volumeMounts:
    - name: config-volume
      mountPath: /config
  volumes:
  - name: config-volume
    configMap:
      name: app-properties
EOF

# 应用Pod
kubectl apply -f pod-with-cm-volume.yaml

# 等待Pod运行
kubectl wait --for=condition=Ready pod/test-cm-volume --timeout=60s

# 查看挂载的配置文件
kubectl exec test-cm-volume -- ls -la /config
kubectl exec test-cm-volume -- cat /config/app.properties
```

**预期输出:**
```
/config 目录内容:
lrwxrwxrwx  app.properties -> ..data/app.properties

/config/app.properties 内容:
database.host=mysql.default.svc.cluster.local
database.port=3306
database.name=myapp
cache.enabled=true
cache.ttl=300
```

**验证点:** ✅ ConfigMap成功挂载为文件

**💡 知识点:**
- volumeMounts: 指定容器内挂载点
- configMap作为volume
- ConfigMap的每个key成为一个文件
- 文件内容就是key的value
- 适合配置文件场景（properties、json、yaml等）
- **Volume挂载支持热更新（约1分钟延迟）**

---

### Step 5: 创建和使用Secret

```bash
# 方式1: 从字面值创建Secret
kubectl create secret generic db-secret \
  --from-literal=username=admin \
  --from-literal=password=P@ssw0rd123

# 查看Secret列表
kubectl get secret

# 查看Secret详情（不显示值）
kubectl describe secret db-secret

# 查看Secret内容（Base64编码）
kubectl get secret db-secret -o yaml

# 手动解码查看（仅用于理解，生产环境谨慎）
kubectl get secret db-secret -o jsonpath='{.data.password}' | base64 -d
echo

# 方式2: 从文件创建Secret
echo -n "my-api-token-12345" > token.txt
kubectl create secret generic api-secret --from-file=token=token.txt

# 立即删除明文文件
rm -f token.txt
```

**预期输出:**
```yaml
data:
  username: YWRtaW4=        # base64("admin")
  password: UEBzc3cwcmQxMjM=  # base64("P@ssw0rd123")

解码结果: P@ssw0rd123
```

**验证点:** ✅ Secret创建成功，数据Base64编码

**💡 知识点:**
- Secret存储敏感信息
- 自动Base64编码
- describe不显示内容（安全）
- 立即删除明文文件
- Base64是编码不是加密，不能防止kubectl get泄露

---

### Step 6: 将Secret注入为环境变量

```bash
cat > pod-with-secret-env.yaml <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: test-secret-env
spec:
  containers:
  - name: test-container
    image: busybox:1.28
    command: ["sh", "-c", "sleep 3600"]
    env:
    - name: DB_USERNAME
      valueFrom:
        secretKeyRef:
          name: db-secret
          key: username
    - name: DB_PASSWORD
      valueFrom:
        secretKeyRef:
          name: db-secret
          key: password
EOF

# 应用Pod
kubectl apply -f pod-with-secret-env.yaml
kubectl wait --for=condition=Ready pod/test-secret-env --timeout=60s

# 验证环境变量（注意：生产环境不要这样做）
kubectl exec test-secret-env -- sh -c 'echo "Username: $DB_USERNAME"'
kubectl exec test-secret-env -- sh -c 'echo "Password length: ${#DB_PASSWORD}"'
```

**预期输出:**
```
Username: admin
Password length: 11
```

**验证点:** ✅ Secret成功注入为环境变量，自动解码

**💡 知识点:**
- secretKeyRef引用Secret
- 自动解码Base64
- 环境变量可能被日志记录（安全风险）
- 生产环境推荐文件挂载方式
- --from-env-file也可以批量注入

---

### Step 7: 将Secret挂载为文件（推荐方式）

```bash
cat > pod-with-secret-volume.yaml <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: test-secret-volume
spec:
  containers:
  - name: test-container
    image: nginx
    volumeMounts:
    - name: secret-volume
      mountPath: /etc/secrets
      readOnly: true
  volumes:
  - name: secret-volume
    secret:
      secretName: db-secret
EOF

# 应用Pod
kubectl apply -f pod-with-secret-volume.yaml
kubectl wait --for=condition=Ready pod/test-secret-volume --timeout=60s

# 查看挂载的Secret文件
kubectl exec test-secret-volume -- ls -la /etc/secrets
kubectl exec test-secret-volume -- cat /etc/secrets/username
kubectl exec test-secret-volume -- cat /etc/secrets/password
```

**预期输出:**
```
/etc/secrets 目录:
-r--------  username
-r--------  password

文件内容（自动解码）:
admin
P@ssw0rd123
```

**验证点:** ✅ Secret成功挂载为文件，自动解码，权限受限

**💡 知识点:**
- readOnly: true 防止修改
- Secret的每个key成为文件
- 自动Base64解码
- 文件权限自动设置为0400
- 更安全：不会被环境变量泄露
- Volume挂载支持Secret热更新

---

### Step 8: 理解配置更新机制

```bash
# 更新ConfigMap（使用--dry-run + apply方式）
kubectl create configmap app-config \
  --from-literal=APP_NAME=MyApp \
  --from-literal=APP_VERSION=2.0 \
  --from-literal=LOG_LEVEL=debug \
  --dry-run=client -o yaml | kubectl apply -f -

# 等待约1分钟后检查Volume挂载的Pod（会自动更新）
echo "等待60秒..."
sleep 65

# Volume挂载方式：会自动更新
# （test-cm-volume使用configMap volume挂载）
echo "Volume挂载方式（自动更新）:"
kubectl exec test-cm-volume -- cat /config/app.properties 2>/dev/null || \
  echo "提示: Pod可能已清理"

# 环境变量方式：不会自动更新
echo "环境变量方式（不会自动更新）:"
kubectl exec test-cm-env -- env | grep APP_VERSION 2>/dev/null || \
  echo "提示: Pod可能已清理"

# 环境变量方式需要重建Pod才能获取新配置
kubectl delete pod test-cm-env 2>/dev/null
kubectl apply -f pod-with-cm-env.yaml
kubectl wait --for=condition=Ready pod/test-cm-env --timeout=60s
kubectl exec test-cm-env -- env | grep APP_VERSION
```

**预期结果:**
```
Volume挂载: 自动更新，约1分钟延迟
环境变量:   需要重建Pod才能获取新配置
重建后:     APP_VERSION=2.0
```

**验证点:** ✅ Volume挂载会热更新，环境变量需重建Pod

**💡 知识点:**
- **Volume挂载**: 支持热更新（约1分钟延迟）
- **环境变量**: 不会自动更新，需重建Pod
- 热更新：应用需监听文件变化
- 建议：版本化ConfigMap名称（如app-config-v2）避免意外更新
- 生产环境滚动更新比热更新更可控

---

## ✅ 验证清单

实验完成后，确认以下要点：

- [ ] 理解ConfigMap和Secret的区别
- [ ] 掌握多种创建ConfigMap的方法
- [ ] 理解环境变量注入方式
- [ ] 掌握Volume挂载方式
- [ ] 了解Secret的Base64编码
- [ ] 理解配置更新机制
- [ ] 知道Volume挂载会自动更新
- [ ] 知道环境变量不会自动更新

---

## 🔧 故障排查

### 问题1: Pod无法启动，ConfigMap不存在

**解决:**
```bash
kubectl get configmap
kubectl describe pod <pod-name>
# 查看Events部分确认错误原因
```

---

### 问题2: Secret解码错误

**解决:**
```bash
# 检查Base64编码
echo -n "your-password" | base64

# 正确创建Secret
kubectl create secret generic my-secret --from-literal=key=value
# 不要手动在YAML中写Base64（容易出错）
```

---

### 问题3: 配置更新不生效

**原因:** 环境变量方式不会自动更新

**解决:**
- 使用Volume挂载方式
- 或重建Pod获取新配置
```bash
kubectl rollout restart deployment/<name>
```

---

### 问题4: Secret内容泄露担忧

**最佳实践:**
```bash
# 限制RBAC权限
kubectl auth can-i get secret --as=<user>

# 使用外部Secret管理（Vault等）
# 启用etcd加密
# 避免在日志中打印Secret值
```

---

### 问题4: kubectl命令超时或API Server连接失败

**现象:**
```
Error from server: etcd cluster is unavailable or misconfigured
The connection to the server was refused
```

**原因:** VM刚启动，K3s尚未完全就绪

**解决:**
```bash
# 等待节点就绪
kubectl wait --for=condition=Ready node --all --timeout=180s

# 检查K3s服务状态
sudo systemctl status k3s

# 等待2-3分钟后重试
```

**预防措施:**
- VM启动后等待2-3分钟再开始实验
- 先运行环境就绪检查
- 确认节点Ready后再进行ConfigMap/Secret操作

---

## 🧪 扩展练习

### 1. 使用YAML创建ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: yaml-config
data:
  key1: value1
  config.json: |
    {
      "setting1": "value1",
      "setting2": "value2"
    }
```

### 2. TLS证书Secret

```bash
# 生产环境TLS证书管理
kubectl create secret tls tls-secret \
  --cert=path/to/cert.crt \
  --key=path/to/key.key
```

### 3. Docker Registry Secret

```bash
# 拉取私有镜像认证
kubectl create secret docker-registry regcred \
  --docker-server=<registry> \
  --docker-username=<user> \
  --docker-password=<password>
```

---

## 📖 知识总结

### ConfigMap vs Secret 对比

| 特性 | ConfigMap | Secret |
|------|-----------|--------|
| 用途 | 非敏感配置 | 敏感信息 |
| 存储 | 明文 | Base64编码 |
| 大小限制 | 1MB | 1MB |
| 使用场景 | 配置文件、参数 | 密码、Token、证书 |
| describe显示 | 显示内容 | 不显示内容 |

### 两种注入方式对比

| 方式 | 优点 | 缺点 | 推荐场景 |
|------|------|------|----------|
| 环境变量 | 简单、快速 | 不会自动更新、可能泄露 | 简单配置 |
| Volume挂载 | 自动更新、更安全 | 应用需读取文件 | 配置文件、Secret |

### 最佳实践

1. **区分敏感和非敏感**
   - 配置用ConfigMap
   - 密码等用Secret

2. **推荐Volume挂载**
   - 支持热更新
   - Secret更安全

3. **版本化管理**
   - ConfigMap命名加版本
   - 避免意外更新

4. **最小权限原则**
   - RBAC限制Secret访问
   - 加密etcd存储

### 工作流程

```
1. 创建ConfigMap/Secret
2. Pod引用ConfigMap/Secret
3. 容器通过环境变量或文件使用配置
4. 更新ConfigMap/Secret
   - Volume挂载: 自动热更新（~1分钟）
   - 环境变量: 重建Pod后生效
```

---

## 🧹 清理环境

```bash
# 删除Pod
kubectl delete pod test-cm-env test-cm-volume test-secret-env test-secret-volume

# 删除ConfigMap
kubectl delete configmap app-config app-properties app-files

# 删除Secret
kubectl delete secret db-secret api-secret

# 删除配置文件
rm -f app.properties server.conf pod-with-cm-env.yaml \
      pod-with-cm-volume.yaml pod-with-secret-env.yaml \
      pod-with-secret-volume.yaml

# 验证清理完成
kubectl get pod,configmap,secret | grep -v "^NAME\|default-token\|kube-"
```

---

## 📎 参考资料

- [ConfigMap官方文档](https://kubernetes.io/docs/concepts/configuration/configmap/)
- [Secret官方文档](https://kubernetes.io/docs/concepts/configuration/secret/)
- [配置最佳实践](https://kubernetes.io/docs/concepts/configuration/overview/)

---

**实验8完成！** 🎉

继续下一个实验前，确保理解：
- ConfigMap和Secret的使用场景区别
- 环境变量和Volume挂载的差异
- 配置热更新的工作机制
- Secret安全使用的最佳实践
