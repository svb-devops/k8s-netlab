#!/usr/bin/env bash
# test-template.sh — 验证 K8s 实验模板 VM 是否健康
#
# 用法：
#   bash scripts/test-template.sh [TEMPLATE_ID]
#
# 示例：
#   bash scripts/test-template.sh 101
#
# 测试内容：
#   1. 从模板克隆测试 VM
#   2. 等待 DHCP 分配 IP
#   3. 等待 SSH 可用
#   4. 等待 K3s 就绪（所有 kube-system pods Running）
#   5. 拉取 nginx 镜像（验证 registry mirror 可用）
#   6. 拉取 busybox 镜像（实验高频镜像）
#   7. 验证 hostname 格式正确（k8s-lab-{vmid}）
#   8. 清理测试 VM
#
# 全部通过退出码 0，任一失败退出码 1。

set -uo pipefail

# --- 配置 ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/../.env"
[ -f "$ENV_FILE" ] && set -a && source "$ENV_FILE" && set +a

TEMPLATE_ID="${1:-${VM_TEMPLATE_ID:-101}}"
PROXMOX_NODE="${PROXMOX_NODE:-pve}"
VM_SSH_USER="${VM_SSH_USER:-root}"
SSH_PASS="${VM_SSH_PASSWORD:-}"
TEST_VMID=""

# --- 颜色输出 ---
PASS=0
FAIL=0
log_ok()   { echo "[OK]   $1"; PASS=$((PASS+1)); }
log_fail() { echo "[FAIL] $1"; FAIL=$((FAIL+1)); }
log_info() { echo "[    ] $1"; }

# --- 清理函数 ---
cleanup() {
    if [ -n "$TEST_VMID" ]; then
        log_info "清理测试 VM ${TEST_VMID}..."
        qm stop "$TEST_VMID" --skiplock 1 2>/dev/null || true
        sleep 3
        qm destroy "$TEST_VMID" 2>/dev/null && log_info "VM ${TEST_VMID} 已删除" || log_info "VM ${TEST_VMID} 删除失败（可手动清理）"
    fi
}
trap cleanup EXIT

# --- 找一个空闲 VMID（100-199 范围）---
find_free_vmid() {
    for id in $(seq 110 199); do
        if ! qm status "$id" &>/dev/null; then
            echo "$id"
            return
        fi
    done
    echo ""
}

echo "================================================"
echo "  K8s 模板健康测试  (模板 VMID: ${TEMPLATE_ID})"
echo "================================================"
echo ""

# --- 检查 0：模板存在 ---
if ! qm config "$TEMPLATE_ID" &>/dev/null; then
    log_fail "模板 VM ${TEMPLATE_ID} 不存在"
    echo ""; echo "测试结果：通过 ${PASS}，失败 ${FAIL}"; exit 1
fi
log_ok "模板 VM ${TEMPLATE_ID} 存在"

# --- 步骤 1：克隆测试 VM ---
TEST_VMID=$(find_free_vmid)
if [ -z "$TEST_VMID" ]; then
    log_fail "100-199 范围内无空闲 VMID"
    exit 1
fi
log_info "克隆模板 ${TEMPLATE_ID} → VM ${TEST_VMID}..."
if qm clone "$TEMPLATE_ID" "$TEST_VMID" --name "test-template-${TEST_VMID}" --full 0 2>&1 | tail -1; then
    log_ok "克隆完成（VM ${TEST_VMID}）"
else
    log_fail "克隆失败"
    TEST_VMID=""
    exit 1
fi

# 调整内存（与生产 VM 一致）
qm set "$TEST_VMID" --memory "${VM_MEMORY_MB:-4096}" --cores "${VM_CORES:-2}" &>/dev/null

# 启动
qm start "$TEST_VMID"
log_info "VM ${TEST_VMID} 已启动，等待 IP..."

# --- 步骤 2：等待 DHCP IP ---
VM_IP=""
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
    log_fail "150s 内未获取到 IP"
    exit 1
fi
log_ok "获取到 IP：${VM_IP}"

# --- 步骤 3：等待 SSH ---
for i in $(seq 1 12); do
    if sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
        "${VM_SSH_USER}@${VM_IP}" 'echo ok' &>/dev/null; then
        break
    fi
    [ "$i" -eq 12 ] && { log_fail "60s 内 SSH 未就绪"; exit 1; }
    sleep 5
done
log_ok "SSH 可用"

# --- 步骤 4：等待 K3s 就绪 ---
log_info "等待 K3s 就绪（最多 150s）..."
K3S_READY=0
for i in $(seq 1 36); do
    # 只统计非 Completed/Succeeded 的 pod（Running + Pending + Init 等）
    # Completed/Succeeded 是 Job 正常结束，不影响集群健康
    COUNTS=$(sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no \
        "${VM_SSH_USER}@${VM_IP}" \
        'kubectl get pods -n kube-system --no-headers 2>/dev/null | awk "
            /Running/   { running++ }
            !/Completed|Succeeded/ { active++ }
            END { print running+0, active+0 }
        "' 2>/dev/null)
    RUNNING=$(echo "$COUNTS" | awk '{print $1}')
    ACTIVE=$(echo "$COUNTS" | awk '{print $2}')
    RUNNING="${RUNNING//[^0-9]/}"
    ACTIVE="${ACTIVE//[^0-9]/}"
    if [ "${RUNNING:-0}" -ge 3 ] && [ "${RUNNING:-0}" -eq "${ACTIVE:-0}" ] && [ "${ACTIVE:-0}" -gt 0 ]; then
        K3S_READY=1
        break
    fi
    sleep 5
done

if [ "$K3S_READY" -eq 0 ]; then
    log_fail "K3s 未在 180s 内就绪（Running=${RUNNING:-?} active=${ACTIVE:-?}）"
    exit 1
fi
log_ok "K3s 就绪（${RUNNING} pods Running）"

# --- 步骤 5：拉取 nginx 镜像 ---
log_info "测试 nginx 镜像拉取（验证 registry mirror）..."
PULL_RESULT=$(sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no \
    "${VM_SSH_USER}@${VM_IP}" \
    'kubectl run nginx-test --image=nginx --restart=Never --command -- sleep 30 2>/dev/null;
     for i in $(seq 1 24); do
       STATUS=$(kubectl get pod nginx-test -o jsonpath="{.status.phase}" 2>/dev/null)
       [ "$STATUS" = "Running" ] && echo "Running" && break
       echo "$STATUS" | grep -qi "error\|backoff" && echo "Error" && break
       sleep 5
     done
     kubectl delete pod nginx-test --ignore-not-found &>/dev/null &' 2>/dev/null)

if echo "$PULL_RESULT" | grep -q "Running"; then
    log_ok "nginx 镜像拉取成功（registry mirror 正常）"
else
    log_fail "nginx 镜像拉取失败（结果: ${PULL_RESULT:-超时}）"
fi

# --- 步骤 6：拉取 busybox 镜像 ---
log_info "测试 busybox:1.28 镜像拉取..."
PULL_RESULT=$(sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no \
    "${VM_SSH_USER}@${VM_IP}" \
    'kubectl run busybox-test --image=busybox:1.28 --restart=Never --command -- sleep 30 2>/dev/null;
     for i in $(seq 1 24); do
       STATUS=$(kubectl get pod busybox-test -o jsonpath="{.status.phase}" 2>/dev/null)
       [ "$STATUS" = "Running" ] && echo "Running" && break
       echo "$STATUS" | grep -qi "error\|backoff" && echo "Error" && break
       sleep 5
     done
     kubectl delete pod busybox-test --ignore-not-found &>/dev/null &' 2>/dev/null)

if echo "$PULL_RESULT" | grep -q "Running"; then
    log_ok "busybox:1.28 镜像拉取成功"
else
    log_fail "busybox:1.28 镜像拉取失败（结果: ${PULL_RESULT:-超时}）"
fi

# --- 步骤 7：验证 hostname 可设置（模拟 reset_k3s_via_agent 行为）---
# 模板初始 hostname 应为 k8s-template；运行时后端会改为 k8s-lab-{vmid}
INIT_HOSTNAME=$(sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no \
    "${VM_SSH_USER}@${VM_IP}" 'hostname' 2>/dev/null)
EXPECTED_INIT="k8s-template"
if [ "$INIT_HOSTNAME" != "$EXPECTED_INIT" ]; then
    log_fail "模板初始 hostname 异常：期望 ${EXPECTED_INIT}，实际 ${INIT_HOSTNAME}"
else
    # 设置为运行时 hostname，验证可生效
    EXPECTED_RUNTIME="k8s-lab-${TEST_VMID}"
    sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no \
        "${VM_SSH_USER}@${VM_IP}" \
        "hostnamectl set-hostname ${EXPECTED_RUNTIME}" 2>/dev/null
    NEW_HOSTNAME=$(sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no \
        "${VM_SSH_USER}@${VM_IP}" 'hostname' 2>/dev/null)
    if [ "$NEW_HOSTNAME" = "$EXPECTED_RUNTIME" ]; then
        log_ok "hostname：模板初始 ${INIT_HOSTNAME} → 运行时 ${NEW_HOSTNAME} ✓"
    else
        log_fail "hostname 设置失败：期望 ${EXPECTED_RUNTIME}，实际 ${NEW_HOSTNAME}"
    fi
fi

# --- 汇总 ---
echo ""
echo "================================================"
echo "  测试完成：通过 ${PASS}，失败 ${FAIL}"
echo "================================================"

[ "$FAIL" -gt 0 ] && exit 1
exit 0
