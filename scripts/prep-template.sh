#!/usr/bin/env bash
# prep-template.sh — 重建 K8s 实验模板（预拉镜像 + 清空 etcd）
#
# 用法：
#   bash scripts/prep-template.sh [NEW_TEMPLATE_VMID]
#
# 流程：
#   1. 从当前模板 full clone → 临时 VM
#   2. 启动，等待 K3s 就绪
#   3. 用 k3s ctr images pull 预拉实验镜像（写入 K3s 自己的 containerd）
#   4. 停止 K3s，清空 etcd
#   5. 关机
#   6. 销毁旧模板，将临时 VM 设为新模板
#
# 镜像策略：
#   - 使用 k3s ctr（不是 crictl / ctr），写入 K3s 独立 containerd socket
#   - latest tag → imagePullPolicy 必须是 IfNotPresent（已在实验 yaml 中设置）
#
# 示例：
#   bash scripts/prep-template.sh          # 使用 .env 中的 VM_TEMPLATE_ID
#   bash scripts/prep-template.sh 199      # 指定临时 VMID（调试）

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/../.env"
[ -f "$ENV_FILE" ] && set -a && source "$ENV_FILE" && set +a

TEMPLATE_ID="${VM_TEMPLATE_ID:-101}"
PROXMOX_NODE="${PROXMOX_NODE:-pve}"
SSH_USER="${VM_SSH_USER:-root}"
SSH_PASS="${VM_SSH_PASSWORD:-}"
GATEWAY="${VM_GATEWAY:-172.16.100.1}"
REGISTRY_MIRROR="${VM_REGISTRY_MIRROR:-http://${GATEWAY}:5000}"

# 临时 VM：199（或用户指定）
TEMP_VMID="${1:-199}"

# 预拉镜像列表（k3s ctr images pull 格式）
# 注意：K3s 默认 registry 是 docker.io，需要加前缀
IMAGES=(
    "docker.io/library/nginx:latest"
    "docker.io/library/busybox:1.28"
    "docker.io/library/httpd:alpine"
    "docker.io/library/redis:alpine"
)

# --- 颜色 ---
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}   $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; }
info() { echo -e "${YELLOW}[....] $1${NC}"; }

TEMP_VM_STARTED=0

cleanup() {
    if [ "$TEMP_VM_STARTED" -eq 1 ] && qm status "$TEMP_VMID" 2>/dev/null | grep -q "running"; then
        info "清理：停止临时 VM ${TEMP_VMID}..."
        qm stop "$TEMP_VMID" --skiplock 1 2>/dev/null || true
    fi
}
trap cleanup EXIT

echo "================================================"
echo "  K8s 模板重建  (模板: ${TEMPLATE_ID} → ${TEMP_VMID})"
echo "================================================"
echo ""

# --- 前置检查 ---
if ! qm config "$TEMPLATE_ID" &>/dev/null; then
    fail "模板 ${TEMPLATE_ID} 不存在"
    exit 1
fi

if qm status "$TEMP_VMID" &>/dev/null; then
    fail "临时 VMID ${TEMP_VMID} 已被占用，请先清理或指定其他 VMID"
    exit 1
fi

if [ -z "$SSH_PASS" ]; then
    fail "VM_SSH_PASSWORD 未设置"
    exit 1
fi

# --- 步骤 1：Full clone ---
info "从模板 ${TEMPLATE_ID} full clone → VM ${TEMP_VMID}..."
if qm clone "$TEMPLATE_ID" "$TEMP_VMID" --name "prep-template-${TEMP_VMID}" --full 1 2>&1 | tail -1; then
    ok "克隆完成"
else
    fail "克隆失败"
    exit 1
fi

qm set "$TEMP_VMID" --memory "${VM_MEMORY_MB:-4096}" --cores "${VM_CORES:-2}" &>/dev/null

# --- 步骤 2：启动 ---
info "启动 VM ${TEMP_VMID}..."
qm start "$TEMP_VMID"
TEMP_VM_STARTED=1

# --- 步骤 3：等待 DHCP IP ---
info "等待 DHCP IP（最多 150s）..."
VM_IP=""
for i in $(seq 1 30); do
    VM_IP=$(qm guest cmd "$TEMP_VMID" network-get-interfaces 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    for iface in data:
        for addr in iface.get('ip-addresses', []):
            ip = addr['ip-address']
            if ip.startswith('172.16.100.'):
                print(ip)
                break
except: pass
" 2>/dev/null)
    [ -n "$VM_IP" ] && break
    sleep 5
done

if [ -z "$VM_IP" ]; then
    fail "未获取到 IP，检查 dnsmasq 和 vmbr1 配置"
    exit 1
fi
ok "IP: ${VM_IP}"

# --- 步骤 4：等待 SSH ---
info "等待 SSH（最多 60s）..."
for i in $(seq 1 12); do
    if sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
        "${SSH_USER}@${VM_IP}" 'echo ok' &>/dev/null; then
        break
    fi
    [ "$i" -eq 12 ] && { fail "SSH 未在 60s 内就绪"; exit 1; }
    sleep 5
done
ok "SSH 可用"

# --- 步骤 5：等待 K3s 就绪 ---
info "等待 K3s 就绪（最多 180s）..."
K3S_OK=0
RUNNING=0
for i in $(seq 1 36); do
    COUNTS=$(sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no \
        "${SSH_USER}@${VM_IP}" \
        'kubectl get pods -n kube-system --no-headers 2>/dev/null | awk "
            /Running/            { running++ }
            !/Completed|Succeeded/ { active++ }
            END { print running+0, active+0 }
        "' 2>/dev/null)
    RUNNING=$(echo "$COUNTS" | awk '{print $1}')
    ACTIVE=$(echo "$COUNTS" | awk '{print $2}')
    RUNNING="${RUNNING//[^0-9]/}"
    ACTIVE="${ACTIVE//[^0-9]/}"
    if [ "${RUNNING:-0}" -ge 3 ] && [ "${RUNNING:-0}" -eq "${ACTIVE:-0}" ] && [ "${ACTIVE:-0}" -gt 0 ]; then
        K3S_OK=1
        break
    fi
    sleep 5
done

if [ "$K3S_OK" -eq 0 ]; then
    fail "K3s 未在 180s 内就绪（Running=${RUNNING:-?}）"
    exit 1
fi
ok "K3s 就绪（${RUNNING} pods Running）"

# --- 步骤 6：预拉镜像 ---
echo ""
info "预拉实验镜像（使用 registry mirror: ${REGISTRY_MIRROR}）..."
echo ""

PULL_FAIL=0
for IMG in "${IMAGES[@]}"; do
    info "  拉取 ${IMG}..."
    # k3s ctr images pull --hosts-dir=/etc/rancher/k3s/registries.yaml 不能直接用
    # 正确姿势：k3s ctr images pull <image> 会自动读取 /etc/rancher/k3s/registries.yaml
    RESULT=$(sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no \
        "${SSH_USER}@${VM_IP}" \
        "k3s ctr images pull '${IMG}' 2>&1 | tail -3" 2>/dev/null)
    if sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no \
        "${SSH_USER}@${VM_IP}" \
        "k3s ctr images check 2>/dev/null | grep -q '${IMG}'" 2>/dev/null; then
        ok "  ${IMG} — 已缓存"
    else
        fail "  ${IMG} — 拉取失败"
        echo "  输出: ${RESULT}"
        PULL_FAIL=$((PULL_FAIL+1))
    fi
done

echo ""
if [ "$PULL_FAIL" -gt 0 ]; then
    fail "${PULL_FAIL} 个镜像拉取失败，中止模板重建"
    exit 1
fi
ok "所有镜像已预拉完成"

# --- 步骤 7：列出已缓存镜像（供确认）---
echo ""
info "当前 K3s 镜像缓存："
sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no \
    "${SSH_USER}@${VM_IP}" \
    'k3s ctr images ls 2>/dev/null | grep -E "nginx|busybox|httpd|redis" | awk "{print \"    \" \$1}"' 2>/dev/null || true

# --- 步骤 8：停止 K3s，清空 etcd ---
echo ""
info "停止 K3s 并清空 etcd 数据（为模板做准备）..."
sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no \
    "${SSH_USER}@${VM_IP}" \
    'systemctl stop k3s 2>/dev/null; sleep 3; rm -rf /var/lib/rancher/k3s/server/db/etcd' 2>/dev/null
ok "K3s 已停止，etcd 已清空"

# 重置 hostname 为模板默认
sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no \
    "${SSH_USER}@${VM_IP}" \
    "hostnamectl set-hostname k8s-template
     sed -i 's/127.0.1.1.*/127.0.1.1 k8s-template/' /etc/hosts" 2>/dev/null
ok "hostname 已重置为 k8s-template"

# --- 步骤 9：关机 ---
info "关机 VM ${TEMP_VMID}..."
sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no \
    "${SSH_USER}@${VM_IP}" 'shutdown -h now' 2>/dev/null || true
TEMP_VM_STARTED=0

# 等待关机完成
for i in $(seq 1 30); do
    STATUS=$(qm status "$TEMP_VMID" 2>/dev/null | awk '{print $2}')
    [ "$STATUS" = "stopped" ] && break
    sleep 3
done
ok "VM ${TEMP_VMID} 已关机"

# --- 步骤 10：确认并替换模板 ---
echo ""
echo "================================================"
echo "  准备替换模板"
echo "  旧模板: VMID ${TEMPLATE_ID}"
echo "  新模板: VMID ${TEMP_VMID} → 将销毁旧模板，设新 VM 为模板"
echo "================================================"
echo ""
echo -n "  确认替换？[y/N] "
read -r CONFIRM
if [ "$CONFIRM" != "y" ] && [ "$CONFIRM" != "Y" ]; then
    echo ""
    info "已取消替换。临时 VM ${TEMP_VMID} 保留，可手动检查后执行："
    echo "    qm destroy ${TEMPLATE_ID}"
    echo "    qm set ${TEMP_VMID} --template 1"
    echo "    # 更新 .env: VM_TEMPLATE_ID=${TEMP_VMID}"
    exit 0
fi

# 销毁旧模板
info "销毁旧模板 ${TEMPLATE_ID}..."
qm destroy "$TEMPLATE_ID" && ok "旧模板已销毁" || { fail "销毁失败，请手动处理"; exit 1; }

# 将临时 VM 设为模板
info "将 VM ${TEMP_VMID} 设为模板..."
qm set "$TEMP_VMID" --template 1 && ok "VM ${TEMP_VMID} 已设为模板" || { fail "设置模板失败"; exit 1; }

echo ""
echo "================================================"
echo -e "  ${GREEN}模板重建完成！${NC}"
echo "  新模板 VMID: ${TEMP_VMID}"
echo ""
echo "  后续操作："
echo "    1. 更新 .env: VM_TEMPLATE_ID=${TEMP_VMID}"
echo "    2. 重启服务: systemctl restart k8s-netlab"
echo "    3. 验证: bash scripts/test-template.sh ${TEMP_VMID}"
echo "================================================"
