# debug-vm

**触发时机**：用户报告 VM 创建失败、克隆超时、用户无法获得实验环境时主动推荐。

系统性排查 VM 创建问题，分四个阶段，每阶段结果决定是否继续。

---

## 阶段一：Proxmox 连接

```bash
curl -sk https://127.0.0.1:8006/api2/json/version | python3 -m json.tool
```

- 返回版本信息 → 继续阶段二
- 连接失败 → 停止，报告：Proxmox API 不可达，检查 `PROXMOX_HOST` 和端口

---

## 阶段二：模板 VM 状态

```bash
# 确认模板 VM 100 存在且在 pool 中
pvesh get /pools/k8s-netlab --output-format json | python3 -c "import sys,json; d=json.load(sys.stdin); print([m for m in d.get('members',[]) if m.get('vmid')==100])"
```

- 模板在 pool 中 → 继续阶段三
- 模板不在 pool → 停止，执行修复：`pvesh set /pools/k8s-netlab --vms 100`，然后重新验证

---

## 阶段三：VMID 范围和容量

```bash
# 检查当前 VM 数量（排除模板）
pvesh get /pools/k8s-netlab --output-format json | python3 -c "
import sys, json
d = json.load(sys.stdin)
vms = [m for m in d.get('members', []) if m.get('type') == 'qemu' and m.get('vmid') != 100]
print(f'当前 VM 数: {len(vms)}, IDs: {[m[\"vmid\"] for m in vms]}')
"
```

- 数量 < `MAX_TOTAL_VMS`（默认 15）→ 继续阶段四
- 已满 → 停止，报告容量已满，建议清理过期 VM

---

## 阶段四：Token 权限验证

```bash
# 用项目 token 尝试读取模板配置（验证 VM.Clone 权限）
source /root/k8s-netlab/.env 2>/dev/null || true
curl -sk -H "Authorization: PVEAPIToken=${PROXMOX_TOKEN_ID}=${PROXMOX_TOKEN_SECRET}" \
  "https://${PROXMOX_HOST}:8006/api2/json/nodes/pve/qemu/100/config" | python3 -m json.tool | head -5
```

- 返回配置 → 权限正常，问题可能在应用层，检查 `journalctl -u k8s-netlab -p err --since "10 minutes ago" --no-pager`
- 403 → Token 无 VM.Clone 权限，需要在 Proxmox 重新绑定角色 `K8SNetLab` 到 pool `/pool/k8s-netlab`

---

## 输出格式

每个阶段报告：`[阶段N] ✅ 通过` 或 `[阶段N] ❌ 失败 — <原因> — <修复动作>`

发现问题立即停止，不继续后续阶段。
