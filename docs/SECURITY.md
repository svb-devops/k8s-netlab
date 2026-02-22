# Security

## Network Isolation Architecture

K8S NetLab implements defense-in-depth network isolation to protect
your infrastructure from experimental VMs.

### Design Principles

1. **Least Privilege** — VMs receive only the network access they need
2. **Defense-in-Depth** — Multiple independent security layers
3. **Default Deny** — All inter-network traffic blocked unless explicitly permitted
4. **Persistent Configuration** — Security rules survive reboots

### Security Layers

#### Layer 1: Network Segmentation

Experimental VMs run on a dedicated isolated network bridge, physically
separated from the host management network. The two networks operate on
distinct subnets with no direct routing between them.

```
Internet
    |
  Router (<GATEWAY_IP>)
    |
  Home Network (example: 10.0.0.0/24)
    |
  PVE Host (<HOST_IP>)
    |
    +-- vmbr0 (Management — host administration)
    |
    +-- vmbr1 (Isolated — 172.16.100.0/24)
          |
          +-- K8S NetLab VMs (DHCP: 172.16.100.10-254)
                |
                +-- ✅ Internet access (via NAT)
                +-- ❌ Home network: BLOCKED
                +-- ❌ Host management: BLOCKED
```

> **Note:** Network addresses shown above are illustrative examples.
> Replace `<GATEWAY_IP>` and `<HOST_IP>` with values appropriate
> to your environment when deploying.

#### Layer 2: Stateful Packet Filtering (iptables)

**FORWARD chain** — controls traffic routed between networks:

| Rule | Source              | Destination         | Action |
|------|---------------------|---------------------|--------|
| 1    | vmbr1 → vmbr1       | any                 | ACCEPT |
| 2    | VM subnet           | Home network        | DROP   |
| 3    | Home network        | VM subnet           | DROP   |
| 4    | vmbr1 → vmbr0       | any (internet)      | ACCEPT |
| 5    | vmbr0 → vmbr1       | ESTABLISHED/RELATED | ACCEPT |

**Rule ordering is critical:** DROP rules (2, 3) are positioned before
the broad ACCEPT rule (4). Rule 1 only matches intra-vmbr1 traffic
(out=vmbr1), so it cannot be used to bypass cross-network DROP rules.

**INPUT chain** — protects the host itself from VM-originated traffic:

| Rule | Interface | Destination | Action |
|------|-----------|-------------|--------|
| 1    | vmbr1     | Host IP     | DROP   |

This prevents VMs from accessing host management services
(SSH, Proxmox Web UI) even though those services are bound to a
different network interface.

#### Layer 3: NAT

VMs access the internet via MASQUERADE NAT on the host. Outbound
traffic is source-NATted to the host's external IP; return traffic
is matched by connection tracking and forwarded back to the originating VM.

#### Layer 4: Persistent Configuration

Rules are managed by `netfilter-persistent` and saved to
`/etc/iptables/rules.v4`. They are automatically restored on every boot,
verified to survive full system restarts.

---

### Security Properties Verified

| Property                              | Status  |
|---------------------------------------|---------|
| VM → Home network devices: BLOCKED    | ✅ Verified |
| VM → Host management (SSH/WebUI): BLOCKED | ✅ Verified |
| VM → Internet: PERMITTED              | ✅ Verified |
| VM ↔ VM (same segment): PERMITTED     | ✅ Verified |
| Rules survive reboot                  | ✅ Verified |
| No FORWARD bypass via rule ordering   | ✅ Verified |

---

### Deployment Checklist

Before deploying to production:

- [ ] Choose non-conflicting IP ranges for the isolated network
- [ ] Substitute all `<HOST_IP>` / `<GATEWAY_IP>` placeholders with real values
- [ ] Verify isolation with `ping` from a test VM before running student workloads
- [ ] Confirm `netfilter-persistent` is enabled: `systemctl is-enabled netfilter-persistent`
- [ ] Test rule persistence: reboot, then re-run the verification checks

### Security Scope and Limitations

This isolation protects the **home network** from VMs. It does **not**:

- Isolate VMs from each other (by design — students need inter-VM networking)
- Protect against attacks that exploit the host kernel or hypervisor itself
- Replace proper credential management or patching

### Reporting Vulnerabilities

If you discover a security issue, please open a
[GitHub Security Advisory](https://github.com/svb-devops/k8s-netlab/security/advisories/new)
rather than a public issue.

---

### Compliance Alignment

This architecture follows principles from:

- **NIST SP 800-125B** — Secure Virtual Network Configuration for Virtual Machine (VM) Protection
- **CIS Critical Security Control 12** — Network Infrastructure Management
- **Defense-in-Depth** architectural pattern
