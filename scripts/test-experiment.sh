#!/usr/bin/env bash
# test-experiment.sh — 自动验证 K8s 实验命令是否可执行
#
# 用法：
#   bash scripts/test-experiment.sh <N>        # 测试单个实验 (1-11)
#   bash scripts/test-experiment.sh all        # 测试所有实验（复用同一VM）
#   bash scripts/test-experiment.sh <N> <VMID> # 复用已有VM（跳过克隆/销毁）
#
# 示例：
#   bash scripts/test-experiment.sh 1
#   bash scripts/test-experiment.sh 3
#   bash scripts/test-experiment.sh all
#   bash scripts/test-experiment.sh 1 150      # 复用 VMID=150 的已有 VM
#
# 测试策略：验证每个实验的"核心假设"，而非完整走读全部步骤
#   实验改动后运行，确保用户不会在步骤中遇到"命令不通"

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/../.env"
[ -f "$ENV_FILE" ] && set -a && source "$ENV_FILE" && set +a

TEMPLATE_ID="${VM_TEMPLATE_ID:-101}"
SSH_USER="${VM_SSH_USER:-root}"
SSH_PASS="${VM_SSH_PASSWORD:-}"

# 测试 VM 使用 198（避免与 prep-template.sh 的 199 冲突）
TEST_VMID="${3:-198}"
MANAGE_VM=1  # 1=自己创建并销毁；0=复用外部传入的 VM

EXP_NUM="${1:-}"
REUSE_VMID="${2:-}"

# 如果指定了复用 VMID，则不管理 VM 生命周期
if [ -n "$REUSE_VMID" ]; then
    TEST_VMID="$REUSE_VMID"
    MANAGE_VM=0
fi

# --- 颜色输出 ---
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'
ok()    { echo -e "    ${GREEN}✅ PASS${NC}  $1"; PASS_COUNT=$((PASS_COUNT+1)); }
fail()  { echo -e "    ${RED}❌ FAIL${NC}  $1"; FAIL_COUNT=$((FAIL_COUNT+1)); }
info()  { echo -e "    ${YELLOW}....${NC}  $1"; }
header(){ echo -e "\n${CYAN}━━━ $1 ━━━${NC}"; }

PASS_COUNT=0
FAIL_COUNT=0
VM_IP=""
VM_STARTED=0

# --- SSH 辅助函数 ---
ssh_run() {
    sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
        "${SSH_USER}@${VM_IP}" "$@" 2>/dev/null
}

ssh_check() {
    # 执行命令，返回是否成功（0=pass）
    ssh_run "$1" >/dev/null 2>&1
}

ssh_out() {
    ssh_run "$1" 2>/dev/null || true
}

# --- 等待 pod 就绪 ---
wait_pod_ready() {
    local selector="$1"
    local max_wait="${2:-60}"
    ssh_run "kubectl wait --for=condition=Ready pod -l ${selector} --timeout=${max_wait}s 2>/dev/null" >/dev/null 2>&1
}

# --- 清理实验资源 ---
cleanup_exp() {
    info "清理实验资源..."
    ssh_run "
        kubectl delete pod --all --ignore-not-found --wait=false 2>/dev/null
        kubectl delete deployment,svc,ingress,networkpolicy,pvc,configmap,secret,statefulset \
            --all --ignore-not-found --wait=false 2>/dev/null
        kubectl delete ns test-ns --ignore-not-found --wait=false 2>/dev/null
        sleep 3
    " >/dev/null 2>&1 || true
}

# ================================================================
# 实验测试函数
# ================================================================

test_exp_1() {
    header "实验1: K8s网络模型基础验证"

    # 1a. 两个 Pod 能各自拿到 IP
    info "创建两个 busybox Pod..."
    ssh_run "
        kubectl run bb1 --image=busybox:1.28 --restart=Never --command -- sleep 300
        kubectl run bb2 --image=busybox:1.28 --restart=Never --command -- sleep 300
        kubectl wait --for=condition=Ready pod/bb1 pod/bb2 --timeout=90s
    " >/dev/null 2>&1

    POD1_IP=$(ssh_out "kubectl get pod bb1 -o jsonpath='{.status.podIP}'")
    POD2_IP=$(ssh_out "kubectl get pod bb2 -o jsonpath='{.status.podIP}'")

    if [ -n "$POD1_IP" ] && [ -n "$POD2_IP" ]; then
        ok "Pod 各自拿到 IP: bb1=${POD1_IP} bb2=${POD2_IP}"
    else
        fail "Pod 未能获取 IP (bb1=${POD1_IP:-?} bb2=${POD2_IP:-?})"
        return 1
    fi

    # 1b. Pod 间 ping
    if ssh_run "kubectl exec bb1 -- ping -c 2 -W 2 ${POD2_IP}" >/dev/null 2>&1; then
        ok "Pod 间 ping 通 (bb1→bb2)"
    else
        fail "Pod 间 ping 失败 (bb1→bb2)"
    fi

    # 1c. Node 到 Pod HTTP
    info "创建 nginx Pod 测试 Node→Pod 通信..."
    ssh_run "
        kubectl run nginx-node-test --image=nginx --restart=Never
        kubectl wait --for=condition=Ready pod/nginx-node-test --timeout=90s
    " >/dev/null 2>&1
    NGINX_IP=$(ssh_out "kubectl get pod nginx-node-test -o jsonpath='{.status.podIP}'")
    if ssh_run "curl -sf --max-time 5 http://${NGINX_IP}" >/dev/null 2>&1; then
        ok "Node→Pod HTTP 通 (nginx ${NGINX_IP})"
    else
        fail "Node→Pod HTTP 失败 (nginx ${NGINX_IP:-?})"
    fi

    # 1d. DNS 解析
    if ssh_run "kubectl exec bb1 -- nslookup kubernetes.default" >/dev/null 2>&1; then
        ok "DNS 解析正常 (kubernetes.default)"
    else
        fail "DNS 解析失败"
    fi

    cleanup_exp
}

test_exp_2() {
    header "实验2: Pod网络实现原理深入探索"

    info "创建 busybox Pod..."
    ssh_run "
        kubectl run probe --image=busybox:1.28 --restart=Never --command -- sleep 300
        kubectl wait --for=condition=Ready pod/probe --timeout=90s
    " >/dev/null 2>&1

    # 2a. Pod 有 eth0 接口
    if ssh_run "kubectl exec probe -- ip addr show eth0" >/dev/null 2>&1; then
        ok "Pod eth0 网络接口存在"
    else
        fail "Pod eth0 不存在"
    fi

    # 2b. 路由表可读
    if ssh_run "kubectl exec probe -- ip route" >/dev/null 2>&1; then
        ok "Pod 路由表可读"
    else
        fail "Pod 路由表读取失败"
    fi

    # 2c. 宿主机有 veth pair
    VETH_COUNT=$(ssh_out "ip link show type veth 2>/dev/null | grep -c 'veth' || echo 0")
    if [ "${VETH_COUNT:-0}" -gt 0 ]; then
        ok "宿主机存在 veth pair (${VETH_COUNT} 个)"
    else
        fail "宿主机未发现 veth pair"
    fi

    # 2d. CNI 配置文件存在
    if ssh_run "ls /var/lib/rancher/k3s/agent/etc/cni/net.d/" >/dev/null 2>&1; then
        ok "K3s CNI 配置文件存在"
    else
        fail "K3s CNI 配置文件未找到"
    fi

    cleanup_exp
}

test_exp_3() {
    header "实验3: Service负载均衡机制"

    info "创建 nginx Deployment + Service..."
    ssh_run "
        kubectl create deployment nginx-app --image=nginx --replicas=2
        kubectl wait --for=condition=Ready pod -l app=nginx-app --timeout=120s
        kubectl expose deployment nginx-app --port=80 --target-port=80 --name=nginx-svc
    " >/dev/null 2>&1

    SVC_IP=$(ssh_out "kubectl get svc nginx-svc -o jsonpath='{.spec.clusterIP}'")

    # 3a. ClusterIP 已分配
    if [ -n "$SVC_IP" ] && [ "$SVC_IP" != "None" ]; then
        ok "Service ClusterIP 已分配: ${SVC_IP}"
    else
        fail "Service ClusterIP 未分配"
        cleanup_exp
        return 1
    fi

    # 3b. 通过 ClusterIP 能访问 nginx
    if ssh_run "curl -sf --max-time 5 http://${SVC_IP}" >/dev/null 2>&1; then
        ok "ClusterIP 访问 nginx 成功 (http://${SVC_IP})"
    else
        fail "ClusterIP 访问失败 (http://${SVC_IP})"
    fi

    # 3c. Endpoints 已注册
    EP_COUNT=$(ssh_out "kubectl get endpoints nginx-svc -o jsonpath='{.subsets[0].addresses}' | python3 -c 'import sys,json; d=json.load(sys.stdin); print(len(d))' 2>/dev/null || echo 0")
    if [ "${EP_COUNT:-0}" -ge 2 ]; then
        ok "Endpoints 已注册 (${EP_COUNT} 个地址)"
    else
        fail "Endpoints 数量不足 (${EP_COUNT:-?}，期望≥2)"
    fi

    cleanup_exp
}

test_exp_4() {
    header "实验4: Ingress控制器详解"

    # 4a. Traefik 已运行
    TRAEFIK_STATUS=$(ssh_out "kubectl get pod -n kube-system -l app.kubernetes.io/name=traefik -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo ''")
    if [ "$TRAEFIK_STATUS" = "Running" ]; then
        ok "Traefik Ingress 控制器运行中"
    else
        fail "Traefik 未运行 (status=${TRAEFIK_STATUS:-未找到})"
    fi

    # 4b. 创建 Deployment + Service + Ingress
    info "创建 web1 deployment + ingress..."
    ssh_run "
        kubectl create deployment web1 --image=nginx --replicas=1
        kubectl wait --for=condition=Ready pod -l app=web1 --timeout=90s
        kubectl expose deployment web1 --port=80 --name=web1-svc
        cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: web1-ingress
  annotations:
    traefik.ingress.kubernetes.io/router.entrypoints: web
spec:
  rules:
  - host: web1.local
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: web1-svc
            port:
              number: 80
EOF
    " >/dev/null 2>&1

    # 4c. Ingress 已创建
    if ssh_run "kubectl get ingress web1-ingress" >/dev/null 2>&1; then
        ok "Ingress 资源已创建"
    else
        fail "Ingress 创建失败"
    fi

    # 4d. 通过 host header 访问
    TRAEFIK_SVC_IP=$(ssh_out "kubectl get svc -n kube-system traefik -o jsonpath='{.spec.clusterIP}' 2>/dev/null || echo ''")
    if [ -n "$TRAEFIK_SVC_IP" ]; then
        if ssh_run "curl -sf --max-time 5 -H 'Host: web1.local' http://${TRAEFIK_SVC_IP}" >/dev/null 2>&1; then
            ok "Ingress 路由正常 (Host: web1.local → nginx)"
        else
            fail "Ingress 路由失败 (Host: web1.local → ${TRAEFIK_SVC_IP})"
        fi
    else
        fail "Traefik ClusterIP 未找到"
    fi

    cleanup_exp
}

test_exp_5() {
    header "实验5: NetworkPolicy网络策略"

    info "创建 server + client Pod 和 NetworkPolicy..."
    ssh_run "
        kubectl run server --image=nginx --restart=Never --labels='role=server'
        kubectl wait --for=condition=Ready pod/server --timeout=90s
        kubectl expose pod server --port=80 --name=server-svc
        kubectl run client --image=busybox:1.28 --restart=Never --labels='role=client' --command -- sleep 300
        kubectl run blocked --image=busybox:1.28 --restart=Never --labels='role=blocked' --command -- sleep 300
        kubectl wait --for=condition=Ready pod/client pod/blocked --timeout=90s
    " >/dev/null 2>&1

    SERVER_IP=$(ssh_out "kubectl get svc server-svc -o jsonpath='{.spec.clusterIP}'")

    # 5a. 策略前：两个 client 都能访问
    if ssh_run "kubectl exec client -- wget -qO- --timeout=5 http://${SERVER_IP}" >/dev/null 2>&1; then
        ok "NetworkPolicy 应用前：client 可访问 server"
    else
        fail "策略前 client 无法访问 server (${SERVER_IP:-?})"
    fi

    # 5b. 应用 NetworkPolicy：只允许 role=client
    ssh_run "
        cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-client-only
spec:
  podSelector:
    matchLabels:
      run: server
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          role: client
    ports:
    - protocol: TCP
      port: 80
EOF
    " >/dev/null 2>&1
    sleep 2

    # 5c. client 仍能访问
    if ssh_run "kubectl exec client -- wget -qO- --timeout=5 http://${SERVER_IP}" >/dev/null 2>&1; then
        ok "NetworkPolicy 应用后：允许的 client 仍可访问"
    else
        fail "NetworkPolicy 应用后：allowed client 被错误拦截"
    fi

    # 5d. blocked Pod 无法访问（期望失败）
    if ! ssh_run "kubectl exec blocked -- wget -qO- --timeout=5 http://${SERVER_IP}" >/dev/null 2>&1; then
        ok "NetworkPolicy 有效：blocked Pod 已被拦截"
    else
        fail "NetworkPolicy 无效：blocked Pod 仍能访问 server"
    fi

    cleanup_exp
}

test_exp_6() {
    header "实验6: DNS服务发现"

    info "创建 DNS 测试环境..."
    ssh_run "
        kubectl run dns-client --image=busybox:1.28 --restart=Never --command -- sleep 300
        kubectl create deployment web --image=nginx --replicas=1
        kubectl wait --for=condition=Ready pod/dns-client --timeout=90s
        kubectl wait --for=condition=Ready pod -l app=web --timeout=90s
        kubectl expose deployment web --port=80 --name=web-svc
    " >/dev/null 2>&1

    # 6a. 解析 kubernetes.default
    if ssh_run "kubectl exec dns-client -- nslookup kubernetes.default" >/dev/null 2>&1; then
        ok "nslookup kubernetes.default 成功"
    else
        fail "nslookup kubernetes.default 失败"
    fi

    # 6b. 解析 Service 名称
    if ssh_run "kubectl exec dns-client -- nslookup web-svc" >/dev/null 2>&1; then
        ok "Service DNS 解析成功 (web-svc)"
    else
        fail "Service DNS 解析失败 (web-svc)"
    fi

    # 6c. 通过 Service 名称访问 HTTP
    if ssh_run "kubectl exec dns-client -- wget -qO- --timeout=10 http://web-svc" >/dev/null 2>&1; then
        ok "通过 Service 名称访问 HTTP 成功 (http://web-svc)"
    else
        fail "通过 Service 名称访问 HTTP 失败"
    fi

    # 6d. FQDN 解析
    if ssh_run "kubectl exec dns-client -- nslookup web-svc.default.svc.cluster.local" >/dev/null 2>&1; then
        ok "FQDN 解析成功 (web-svc.default.svc.cluster.local)"
    else
        fail "FQDN 解析失败"
    fi

    cleanup_exp
}

test_exp_7() {
    header "实验7: 持久化存储 (PV/PVC/StorageClass)"

    # 7a. 查看 StorageClass
    SC=$(ssh_out "kubectl get sc -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo ''")
    if [ -n "$SC" ]; then
        ok "StorageClass 存在: ${SC}"
    else
        fail "未找到 StorageClass"
    fi

    # 7b. 创建 PVC
    ssh_run "
        cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: test-pvc
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 100Mi
EOF
    " >/dev/null 2>&1
    sleep 3

    PVC_STATUS=$(ssh_out "kubectl get pvc test-pvc -o jsonpath='{.status.phase}' 2>/dev/null || echo ''")
    if [ "$PVC_STATUS" = "Bound" ]; then
        ok "PVC 创建并 Bound"
    else
        fail "PVC 未 Bound (status=${PVC_STATUS:-?})"
    fi

    # 7c. Pod 挂载 PVC 并写入数据
    ssh_run "
        cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: pvc-test-pod
spec:
  containers:
  - name: writer
    image: busybox:1.28
    command: [sh, -c, 'echo hello-pvc > /data/test.txt && sleep 30']
    volumeMounts:
    - name: data
      mountPath: /data
  volumes:
  - name: data
    persistentVolumeClaim:
      claimName: test-pvc
  restartPolicy: Never
EOF
        kubectl wait --for=condition=Ready pod/pvc-test-pod --timeout=60s
    " >/dev/null 2>&1

    DATA=$(ssh_out "kubectl exec pvc-test-pod -- cat /data/test.txt 2>/dev/null || echo ''")
    if [ "$DATA" = "hello-pvc" ]; then
        ok "Pod 挂载 PVC 并写入数据成功"
    else
        fail "PVC 数据读写失败 (读到: ${DATA:-空})"
    fi

    cleanup_exp
}

test_exp_8() {
    header "实验8: ConfigMap和Secret配置管理"

    # 8a. 创建 ConfigMap
    ssh_run "
        kubectl create configmap app-config \
            --from-literal=APP_ENV=test \
            --from-literal=LOG_LEVEL=debug
    " >/dev/null 2>&1

    # 8b. 创建 Secret
    ssh_run "
        kubectl create secret generic app-secret \
            --from-literal=DB_PASSWORD=supersecret123
    " >/dev/null 2>&1

    # 8c. Pod 通过环境变量消费 ConfigMap
    ssh_run "
        cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: config-test
spec:
  containers:
  - name: app
    image: busybox:1.28
    command: [sh, -c, 'echo \$APP_ENV && echo \$DB_PASSWORD && sleep 30']
    env:
    - name: APP_ENV
      valueFrom:
        configMapKeyRef:
          name: app-config
          key: APP_ENV
    - name: DB_PASSWORD
      valueFrom:
        secretKeyRef:
          name: app-secret
          key: DB_PASSWORD
  restartPolicy: Never
EOF
        kubectl wait --for=condition=Ready pod/config-test --timeout=60s
    " >/dev/null 2>&1

    ENV_OUT=$(ssh_out "kubectl exec config-test -- sh -c 'echo \$APP_ENV' 2>/dev/null || echo ''")
    SECRET_OUT=$(ssh_out "kubectl exec config-test -- sh -c 'echo \$DB_PASSWORD' 2>/dev/null || echo ''")

    if [ "$ENV_OUT" = "test" ]; then
        ok "ConfigMap 环境变量注入成功 (APP_ENV=test)"
    else
        fail "ConfigMap 注入失败 (读到: ${ENV_OUT:-空})"
    fi

    if [ "$SECRET_OUT" = "supersecret123" ]; then
        ok "Secret 环境变量注入成功"
    else
        fail "Secret 注入失败 (读到: ${SECRET_OUT:-空})"
    fi

    cleanup_exp
}

test_exp_9() {
    header "实验9: StatefulSet有状态应用管理"

    # 9a. 创建 Redis StatefulSet
    ssh_run "
        cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: redis
spec:
  selector:
    matchLabels:
      app: redis
  serviceName: redis
  replicas: 1
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
      - name: redis
        image: redis:alpine
        ports:
        - containerPort: 6379
---
apiVersion: v1
kind: Service
metadata:
  name: redis
spec:
  clusterIP: None
  selector:
    app: redis
  ports:
  - port: 6379
EOF
        kubectl wait --for=condition=Ready pod/redis-0 --timeout=120s
    " >/dev/null 2>&1

    # 9a. StatefulSet Pod 名称固定
    POD_NAME=$(ssh_out "kubectl get pod redis-0 -o jsonpath='{.metadata.name}' 2>/dev/null || echo ''")
    if [ "$POD_NAME" = "redis-0" ]; then
        ok "StatefulSet Pod 名称固定 (redis-0)"
    else
        fail "StatefulSet Pod 未就绪 (pod=${POD_NAME:-?})"
    fi

    # 9b. Redis 可响应 PING
    PONG=$(ssh_out "kubectl exec redis-0 -- redis-cli ping 2>/dev/null || echo ''")
    if [ "$PONG" = "PONG" ]; then
        ok "Redis 响应 PING → PONG"
    else
        fail "Redis 未响应 PING (得到: ${PONG:-空})"
    fi

    # 9c. Headless Service DNS
    ssh_run "
        kubectl run dns-test --image=busybox:1.28 --restart=Never --command -- sleep 60
        kubectl wait --for=condition=Ready pod/dns-test --timeout=60s
    " >/dev/null 2>&1
    if ssh_run "kubectl exec dns-test -- nslookup redis-0.redis.default.svc.cluster.local" >/dev/null 2>&1; then
        ok "StatefulSet Pod DNS 解析成功 (redis-0.redis.default.svc.cluster.local)"
    else
        fail "StatefulSet Pod DNS 解析失败"
    fi

    cleanup_exp
}

test_exp_10() {
    header "实验10: 监控和日志"

    # 10a. metrics-server / kubectl top 可用
    info "检查 metrics-server..."
    sleep 5  # 等待上一次 cleanup 完成
    if ssh_run "kubectl top node 2>/dev/null" >/dev/null 2>&1; then
        ok "kubectl top node 可用 (metrics-server 运行)"
    else
        # K3s 默认不包含 metrics-server，这是预期情况
        MS=$(ssh_out "kubectl get pods -n kube-system -l k8s-app=metrics-server -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo ''")
        if [ -z "$MS" ]; then
            ok "metrics-server 未安装 (实验中会手动安装，跳过预检)"
        else
            fail "metrics-server 存在但无法使用 (status=${MS})"
        fi
    fi

    # 10b. kubectl logs 基本功能
    ssh_run "
        kubectl run log-test --image=busybox:1.28 --restart=Never --command -- sh -c 'echo hello-log && sleep 30'
        kubectl wait --for=condition=Ready pod/log-test --timeout=60s
    " >/dev/null 2>&1
    LOG_OUT=$(ssh_out "kubectl logs log-test 2>/dev/null | head -1 || echo ''")
    if [ "$LOG_OUT" = "hello-log" ]; then
        ok "kubectl logs 正常 (读到: hello-log)"
    else
        fail "kubectl logs 失败 (读到: ${LOG_OUT:-空})"
    fi

    # 10c. kubectl describe / events 可用
    if ssh_run "kubectl get events --sort-by=.metadata.creationTimestamp" >/dev/null 2>&1; then
        ok "kubectl events 可读"
    else
        fail "kubectl events 失败"
    fi

    cleanup_exp
}

test_exp_11() {
    header "实验11: 综合实践"

    info "创建完整应用栈（nginx + redis + service）..."
    ssh_run "
        # 前端 nginx
        kubectl create deployment frontend --image=nginx --replicas=2
        # 后端 redis
        kubectl run redis-backend --image=redis:alpine --restart=Never
        kubectl wait --for=condition=Ready pod -l app=frontend --timeout=120s
        kubectl wait --for=condition=Ready pod/redis-backend --timeout=120s
        kubectl expose deployment frontend --port=80 --name=frontend-svc
        kubectl expose pod redis-backend --port=6379 --name=redis-svc
    " >/dev/null 2>&1

    FRONTEND_IP=$(ssh_out "kubectl get svc frontend-svc -o jsonpath='{.spec.clusterIP}'")
    REDIS_IP=$(ssh_out "kubectl get svc redis-svc -o jsonpath='{.spec.clusterIP}'")

    # 11a. 前端可访问
    if ssh_run "curl -sf --max-time 5 http://${FRONTEND_IP}" >/dev/null 2>&1; then
        ok "前端 nginx 可访问 (ClusterIP: ${FRONTEND_IP})"
    else
        fail "前端 nginx 不可访问 (${FRONTEND_IP:-?})"
    fi

    # 11b. Redis 响应
    ssh_run "
        kubectl run redis-cli --image=redis:alpine --restart=Never --command -- sleep 60
        kubectl wait --for=condition=Ready pod/redis-cli --timeout=60s
    " >/dev/null 2>&1
    PONG=$(ssh_out "kubectl exec redis-cli -- redis-cli -h ${REDIS_IP} ping 2>/dev/null || echo ''")
    if [ "$PONG" = "PONG" ]; then
        ok "Redis 后端可访问 (ClusterIP: ${REDIS_IP})"
    else
        fail "Redis 后端不可访问 (${REDIS_IP:-?})"
    fi

    # 11c. Deployment 扩缩容
    ssh_run "kubectl scale deployment frontend --replicas=3" >/dev/null 2>&1
    sleep 5
    READY=$(ssh_out "kubectl get deployment frontend -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo 0")
    if [ "${READY:-0}" -ge 3 ]; then
        ok "扩缩容正常 (replicas → 3, ready=${READY})"
    else
        fail "扩缩容失败 (期望 readyReplicas≥3，实际=${READY:-?})"
    fi

    cleanup_exp
}

# ================================================================
# VM 生命周期管理
# ================================================================

start_test_vm() {
    if [ "$MANAGE_VM" -eq 0 ]; then
        VM_IP=$(qm guest cmd "$TEST_VMID" network-get-interfaces 2>/dev/null | python3 -c "
import sys,json
try:
    data=json.load(sys.stdin)
    for iface in data:
        for addr in iface.get('ip-addresses',[]):
            ip=addr['ip-address']
            if ip.startswith('172.16.100.'):
                print(ip)
                break
except: pass
" 2>/dev/null)
        if [ -z "$VM_IP" ]; then
            echo "错误: 复用 VM ${TEST_VMID} 无法获取 IP"
            exit 1
        fi
        echo "复用 VM ${TEST_VMID} (IP: ${VM_IP})"
        return 0
    fi

    echo ""
    echo "════════════════════════════════════════════════"
    echo "  K8s 实验测试"
    echo "  模板: ${TEMPLATE_ID} → 测试VM: ${TEST_VMID}"
    echo "════════════════════════════════════════════════"

    # 检查 VMID 是否空闲
    if qm status "$TEST_VMID" &>/dev/null; then
        echo "错误: VMID ${TEST_VMID} 已被占用，请先清理或用 --reuse 参数"
        exit 1
    fi

    echo ""
    echo "[1/4] 克隆模板 ${TEMPLATE_ID} → VM ${TEST_VMID}..."
    qm clone "$TEMPLATE_ID" "$TEST_VMID" --name "test-exp-${TEST_VMID}" --full 0 2>&1 | tail -1
    qm set "$TEST_VMID" --memory "${VM_MEMORY_MB:-4096}" --cores "${VM_CORES:-2}" &>/dev/null
    qm start "$TEST_VMID"
    VM_STARTED=1

    echo "[2/4] 等待 IP (最多 150s)..."
    for i in $(seq 1 30); do
        VM_IP=$(qm guest cmd "$TEST_VMID" network-get-interfaces 2>/dev/null | python3 -c "
import sys,json
try:
    data=json.load(sys.stdin)
    for iface in data:
        for addr in iface.get('ip-addresses',[]):
            ip=addr['ip-address']
            if ip.startswith('172.16.100.'):
                print(ip)
                break
except: pass
" 2>/dev/null)
        [ -n "$VM_IP" ] && break
        sleep 5
    done

    if [ -z "$VM_IP" ]; then
        echo "错误: 未获取到 IP"
        exit 1
    fi
    echo "  VM IP: ${VM_IP}"

    echo "[3/4] 等待 SSH (最多 60s)..."
    for i in $(seq 1 12); do
        sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
            "${SSH_USER}@${VM_IP}" 'echo ok' >/dev/null 2>&1 && break
        [ "$i" -eq 12 ] && { echo "错误: SSH 超时"; exit 1; }
        sleep 5
    done

    echo "[4/4] 等待 K3s 就绪 (最多 180s)..."
    K3S_OK=0
    for i in $(seq 1 36); do
        COUNTS=$(sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no \
            "${SSH_USER}@${VM_IP}" \
            'kubectl get pods -n kube-system --no-headers 2>/dev/null | awk "
                /Running/              { r++ }
                !/Completed|Succeeded/ { a++ }
                END { print r+0, a+0 }
            "' 2>/dev/null)
        R=$(echo "$COUNTS" | awk '{print $1}')
        A=$(echo "$COUNTS" | awk '{print $2}')
        R="${R//[^0-9]/}"; A="${A//[^0-9]/}"
        if [ "${R:-0}" -ge 3 ] && [ "${R:-0}" -eq "${A:-0}" ] && [ "${A:-0}" -gt 0 ]; then
            K3S_OK=1
            break
        fi
        sleep 5
    done

    if [ "$K3S_OK" -eq 0 ]; then
        echo "错误: K3s 未就绪"
        exit 1
    fi
    echo ""
    echo "  VM 就绪 ✅  IP=${VM_IP}"
}

destroy_test_vm() {
    [ "$MANAGE_VM" -eq 0 ] && return 0
    [ "$VM_STARTED" -eq 0 ] && return 0
    echo ""
    echo "销毁测试 VM ${TEST_VMID}..."
    qm stop "$TEST_VMID" --skiplock 1 2>/dev/null || true
    sleep 3
    qm destroy "$TEST_VMID" 2>/dev/null && echo "VM ${TEST_VMID} 已删除" || echo "VM ${TEST_VMID} 删除失败（可手动清理）"
}

trap destroy_test_vm EXIT

# ================================================================
# Main
# ================================================================

if [ -z "$EXP_NUM" ]; then
    echo "用法: $0 <实验编号(1-11) | all> [复用VMID]"
    echo "示例: $0 1          # 测试实验1"
    echo "       $0 all        # 测试全部实验"
    echo "       $0 3 150      # 复用VM 150 测试实验3"
    exit 1
fi

# 确定要运行的实验列表
if [ "$EXP_NUM" = "all" ]; then
    EXP_LIST="1 2 3 4 5 6 7 8 9 10 11"
else
    EXP_LIST="$EXP_NUM"
fi

start_test_vm

START_TIME=$(date +%s)

for N in $EXP_LIST; do
    case "$N" in
        1)  test_exp_1 ;;
        2)  test_exp_2 ;;
        3)  test_exp_3 ;;
        4)  test_exp_4 ;;
        5)  test_exp_5 ;;
        6)  test_exp_6 ;;
        7)  test_exp_7 ;;
        8)  test_exp_8 ;;
        9)  test_exp_9 ;;
        10) test_exp_10 ;;
        11) test_exp_11 ;;
        *)
            echo "未知实验编号: ${N}（有效范围 1-11）"
            ;;
    esac
done

END_TIME=$(date +%s)
ELAPSED=$(( END_TIME - START_TIME ))

echo ""
echo "════════════════════════════════════════════════"
echo "  测试完成  耗时 ${ELAPSED}s"
echo "  通过: ${PASS_COUNT}  失败: ${FAIL_COUNT}"
echo "════════════════════════════════════════════════"

[ "$FAIL_COUNT" -gt 0 ] && exit 1
exit 0
