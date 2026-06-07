"""
K8S NetLab - Experiment Documentation API Routes

Provides endpoints to list and serve Markdown experiment documents.
When DIRECTUS_URL is configured, content is fetched from Directus CMS;
otherwise falls back to the hardcoded metadata + local Markdown files.
"""

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Cookie, HTTPException
from fastapi.responses import JSONResponse

from backend.auth import auth_manager
from backend.directus_client import fetch_experiment_detail, fetch_experiment_list

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/experiments", tags=["experiments"])

# Project root and experiments directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS_DIR = PROJECT_ROOT / "docs" / "experiments"

# Experiment metadata (fixed set for MVP v1.0)
EXPERIMENTS = [
    {
        "id": "01",
        "filename": "01-kubernetes-network-basics.md",
        "title": "Kubernetes 网络基础",
        "difficulty": 2,
        "duration": "30-35 分钟",
        "phase": 1,
        "background": (
            "## 实验背景\n\n"
            "Kubernetes 对网络有三条**铁律**，任何合规的 K8s 集群都必须满足：\n\n"
            "1. **Pod 间直连**：任意两个 Pod 不经 NAT 即可互相通信\n"
            "2. **Node→Pod 直连**：节点可直接访问任意 Pod\n"
            "3. **IP-per-Pod**：每个 Pod 有独立 IP，Pod 内容器共享该 IP\n\n"
            "### 为什么这样设计？\n\n"
            "传统 Docker 用 NAT + 端口映射，多容器协作时端口冲突难以管理。"
            "K8s 的 IP-per-Pod 模型让每个 Pod 像独立的「小虚拟机」——"
            "有自己的 IP、端口空间，容器间通过 `localhost` 互通。\n\n"
            "### 本实验验证内容\n\n"
            "| 验证点 | 方法 |\n"
            "|--------|------|\n"
            "| Pod IP 分配 | `kubectl get pod -o wide` |\n"
            "| Pod 间直连 | `kubectl exec` + `ping` / `curl` |\n"
            "| 网络命名空间 | `ip netns` / `ip addr` |\n\n"
            "这是后续所有网络实验的基础——先确认 K8s 网络规则已满足，再研究它是**怎么实现**的。"
        ),
    },
    {
        "id": "02",
        "filename": "02-pod-network-deep-dive.md",
        "title": "Pod 网络深入探索",
        "difficulty": 3,
        "duration": "35-40 分钟",
        "phase": 1,
        "background": (
            "## 实验背景\n\n"
            "实验1 验证了 Pod 网络的**行为**，本实验深入底层看它是**如何实现**的。\n\n"
            "### CNI 插件机制\n\n"
            "K8s 本身不管网络，由 **CNI（Container Network Interface）插件**负责：\n"
            "Pod 创建时，kubelet 调用 CNI 插件为容器配置网络接口、IP 和路由。\n\n"
            "K3s 默认使用 **Flannel**（VXLAN 模式）作为 CNI。\n\n"
            "### 数据包的真实路径\n\n"
            "```\n"
            "Pod A (eth0)\n"
            "  │ veth pair\n"
            "  ▼\n"
            "cni0 网桥（Linux Bridge）\n"
            "  │ Flannel 路由\n"
            "  ▼\n"
            "flannel.1 VXLAN 隧道\n"
            "  │ 物理网卡\n"
            "  ▼\n"
            "Pod B (eth0)\n"
            "```\n\n"
            "### 关键组件\n\n"
            "- **veth pair**：两头一对虚拟网卡，一端在 Pod 命名空间，一端在宿主机\n"
            "- **cni0 网桥**：相当于软件交换机，连接本节点所有 Pod\n"
            "- **flannel.1**：跨节点隧道接口（单节点实验可观察但不触发）"
        ),
    },
    {
        "id": "03",
        "filename": "03-service-loadbalancing.md",
        "title": "Service 负载均衡",
        "difficulty": 3,
        "duration": "35-40 分钟",
        "phase": 1,
        "background": (
            "## 实验背景\n\n"
            "Pod IP 是**不稳定的**——Pod 重启后 IP 会变。"
            "**Service** 是 K8s 对这一问题的根本解决方案：提供稳定虚拟 IP + DNS 名称 + 负载均衡。\n\n"
            "### 三种 Service 类型\n\n"
            "| 类型 | 访问范围 | 典型用途 |\n"
            "|------|----------|----------|\n"
            "| ClusterIP | 集群内部 | 微服务间调用 |\n"
            "| NodePort | 节点 IP:端口 | 开发测试对外暴露 |\n"
            "| LoadBalancer | 云厂商 LB | 生产对外入口 |\n\n"
            "### kube-proxy 的作用\n\n"
            "Service 本质是 **kube-proxy** 在每台节点上维护的 iptables/IPVS 规则。"
            "访问 ClusterIP 时，iptables 规则随机选择一个健康 Pod 并 DNAT 到其真实 IP。\n\n"
            "### Endpoint\n\n"
            "Service 通过 **Endpoint** 对象跟踪后端 Pod 列表。"
            "Pod 就绪时自动加入，Pod 不健康时自动摘除——这是 K8s 自愈能力的体现。"
        ),
    },
    {
        "id": "04",
        "filename": "04-ingress-controller.md",
        "title": "Ingress 控制器详解",
        "difficulty": 4,
        "duration": "45-50 分钟",
        "phase": 2,
        "background": (
            "## 实验背景\n\n"
            "NodePort 每个服务占一个端口，管理混乱；LoadBalancer 每个服务消耗一个云 IP，代价高昂。"
            "**Ingress** 是 K8s 的 7 层 HTTP 路由方案——一个入口，通过域名/路径路由到多个 Service。\n\n"
            "### Ingress 工作原理\n\n"
            "```\n"
            "外部请求\n"
            "  │\n"
            "  ▼\n"
            "Ingress Controller（Traefik/Nginx）\n"
            "  │ 读取 Ingress 规则\n"
            "  ├─ /app-a  →  service-a:80\n"
            "  └─ /app-b  →  service-b:80\n"
            "```\n\n"
            "### K3s 内置 Traefik\n\n"
            "K3s 默认安装 **Traefik** 作为 Ingress Controller，已在集群中运行。"
            "Traefik 监听 Ingress 资源变化，自动更新路由规则——无需手动 reload。\n\n"
            "### 两种路由方式\n\n"
            "- **基于路径**：`lab.example.com/api` → 后端服务，`lab.example.com/web` → 前端服务\n"
            "- **基于主机名**：`api.example.com` vs `web.example.com` 路由到不同服务\n\n"
            "生产环境通常两者结合，配合 TLS 证书实现 HTTPS 统一入口。"
        ),
    },
    {
        "id": "05",
        "filename": "05-network-policy.md",
        "title": "NetworkPolicy 网络策略",
        "difficulty": 3,
        "duration": "35-40 分钟",
        "phase": 2,
        "background": (
            "## 实验背景\n\n"
            "默认情况下，K8s 集群中**所有 Pod 互相可达**——这在生产环境是安全隐患。"
            "**NetworkPolicy** 是 K8s 原生的网络防火墙，基于标签选择器控制 Pod 级别的流量。\n\n"
            "### 工作原理\n\n"
            "NetworkPolicy 不自己执行规则，而是由 **CNI 插件**（如 Calico、Cilium）实现。"
            "K3s 默认的 Flannel **不支持** NetworkPolicy，实验环境已切换为 Calico 或使用 kube-router。\n\n"
            "### 白名单模型\n\n"
            "一旦给 Pod 应用了 NetworkPolicy，**默认拒绝所有未显式允许的流量**（白名单）。\n\n"
            "| 规则类型 | 控制方向 |\n"
            "|----------|----------|\n"
            "| Ingress（入站）| 谁能访问我 |\n"
            "| Egress（出站）| 我能访问谁 |\n\n"
            "### 典型场景\n\n"
            "- 数据库只允许后端 Pod 访问，拒绝其他所有来源\n"
            "- 前端 Pod 只能访问 API 服务，不能直连数据库\n"
            "- 某 Namespace 完全隔离，不允许跨 Namespace 通信"
        ),
    },
    {
        "id": "06",
        "filename": "06-dns-service-discovery.md",
        "title": "DNS 服务发现",
        "difficulty": 3,
        "duration": "35-40 分钟",
        "phase": 2,
        "background": (
            "## 实验背景\n\n"
            "在微服务架构中，服务之间如何互相找到对方？"
            "K8s 的答案是 **DNS 服务发现**：每个 Service 自动获得一个 DNS 名称，"
            "不需要硬编码 IP，Pod 重建后 DNS 名称不变。\n\n"
            "### CoreDNS\n\n"
            "K8s 集群内置 **CoreDNS**，负责解析所有 `*.svc.cluster.local` 域名。"
            "每个 Pod 的 `/etc/resolv.conf` 指向 CoreDNS，使 DNS 查询自动走集群内部。\n\n"
            "### DNS 记录格式\n\n"
            "| 类型 | 格式 |\n"
            "|------|------|\n"
            "| 同 Namespace 短名 | `service-name` |\n"
            "| 跨 Namespace | `service-name.namespace` |\n"
            "| 完整 FQDN | `service-name.namespace.svc.cluster.local` |\n\n"
            "### Headless Service 的特殊性\n\n"
            "普通 Service DNS 解析返回 **ClusterIP**（虚拟 IP）。\n"
            "Headless Service（`clusterIP: None`）DNS 解析直接返回**每个 Pod 的真实 IP**，"
            "让客户端自主选择 Pod——StatefulSet 依赖这一特性实现稳定的 Pod 寻址。"
        ),
    },
    {
        "id": "07",
        "filename": "07-persistent-storage.md",
        "title": "持久化存储 PV/PVC",
        "difficulty": 3,
        "duration": "40-45 分钟",
        "phase": 3,
        "background": (
            "## 实验背景\n\n"
            "容器是**无状态的**——重启后文件系统恢复初始状态。"
            "数据库、日志、用户上传文件需要持久化，K8s 用三层抽象解决这个问题。\n\n"
            "### 三层存储抽象\n\n"
            "```\n"
            "StorageClass（如何提供存储）\n"
            "  ↓ 动态供应\n"
            "PersistentVolume - PV（实际存储资源）\n"
            "  ↓ 绑定\n"
            "PersistentVolumeClaim - PVC（Pod 的存储申请）\n"
            "  ↓ 挂载\n"
            "Pod（使用存储）\n"
            "```\n\n"
            "### 关注点分离\n\n"
            "- **管理员**：创建 PV 或配置 StorageClass（关心底层存储类型）\n"
            "- **开发者**：创建 PVC，声明需要多大存储（不关心底层）\n\n"
            "### K3s local-path-provisioner\n\n"
            "K3s 内置 **local-path** StorageClass，动态在节点本地创建目录作为 PV。"
            "适合单节点实验，生产环境通常用 Ceph、NFS 或云存储。\n\n"
            "**关键验证**：删除 Pod 再重建，数据依然存在——这是 PV 的核心价值。"
        ),
    },
    {
        "id": "08",
        "filename": "08-configmap-secret.md",
        "title": "ConfigMap 和 Secret",
        "difficulty": 3,
        "duration": "35-40 分钟",
        "phase": 3,
        "background": (
            "## 实验背景\n\n"
            "**12-Factor App** 原则第三条：配置与代码分离。"
            "把数据库地址、API Key 硬编码进镜像，意味着同一镜像无法在不同环境运行。\n\n"
            "### ConfigMap vs Secret\n\n"
            "| | ConfigMap | Secret |\n"
            "|-|-----------|--------|\n"
            "| 用途 | 非敏感配置 | 密码、证书、Token |\n"
            "| 存储 | 明文 | Base64 编码（etcd 可加密）|\n"
            "| 典型内容 | 端口号、日志级别、特性开关 | DB 密码、TLS 私钥 |\n\n"
            "### 两种注入方式\n\n"
            "1. **环境变量**：`env.valueFrom.configMapKeyRef` — 简单，但变更需重启 Pod\n"
            "2. **Volume 挂载**：文件方式挂载，支持**热更新**（约 1 分钟内生效，无需重启）\n\n"
            "### 安全最佳实践\n\n"
            "- Secret 不要提交到 Git（用 Sealed Secret 或外部 Vault 管理）\n"
            "- 只给 Pod 挂载它需要的 Secret，遵循最小权限原则\n"
            "- 生产环境开启 etcd Secret 加密"
        ),
    },
    {
        "id": "09",
        "filename": "09-statefulset.md",
        "title": "StatefulSet 有状态应用",
        "difficulty": 4,
        "duration": "45-50 分钟",
        "phase": 4,
        "background": (
            "## 实验背景\n\n"
            "Deployment 的 Pod 是匿名、可替换的（牲畜模式）。"
            "数据库、消息队列等有状态应用需要**稳定标识**——"
            "**StatefulSet** 专为此设计。\n\n"
            "### StatefulSet 的三大保证\n\n"
            "| 保证 | 具体表现 |\n"
            "|------|----------|\n"
            "| 稳定网络标识 | Pod 名固定：`web-0`, `web-1`（不随机）|\n"
            "| 独立持久存储 | 每个 Pod 有自己的 PVC，不共享 |\n"
            "| 有序部署/销毁 | 0→1→2 顺序创建，2→1→0 顺序删除 |\n\n"
            "### 与 Deployment 的本质区别\n\n"
            "```\n"
            "Deployment:   web-xk8f2  web-m9p3q  （随机 hash，可互换）\n"
            "StatefulSet:  web-0      web-1      （固定序号，各有状态）\n"
            "```\n\n"
            "### 配套 Headless Service\n\n"
            "StatefulSet 必须搭配 Headless Service，这样每个 Pod 可通过"
            " `web-0.service-name` 直接 DNS 寻址。"
            "这正是 MySQL 主从、ZooKeeper 集群等应用所需要的。"
        ),
    },
    {
        "id": "10",
        "filename": "10-monitoring-logging.md",
        "title": "监控和日志管理",
        "difficulty": 3,
        "duration": "35-40 分钟",
        "phase": 4,
        "background": (
            "## 实验背景\n\n"
            "在 K8s 中，传统的「SSH 进服务器看日志」行不通——"
            "Pod 随时可能被调度到不同节点，数量也动态变化。"
            "K8s 提供了**原生**的日志和监控能力。\n\n"
            "### 日志体系\n\n"
            "K8s 日志分三层：\n\n"
            "1. **容器日志**：`kubectl logs` 直接查看 stdout/stderr\n"
            "2. **节点日志**：`/var/log/pods/` 目录下的文件\n"
            "3. **集群日志**：需要 EFK/Loki 等日志聚合系统（超出本实验范围）\n\n"
            "### 资源监控\n\n"
            "**metrics-server** 是 K8s 官方轻量监控组件，提供 CPU/内存实时指标：\n\n"
            "- `kubectl top node` — 节点资源使用\n"
            "- `kubectl top pod` — Pod 资源使用\n"
            "- HPA（水平自动扩缩）依赖 metrics-server 数据\n\n"
            "### Events 事件系统\n\n"
            "`kubectl describe pod` 中的 Events 是排查问题的**第一现场**：\n"
            "镜像拉取失败、OOM、调度失败等都会在这里留下记录，保留 1 小时。"
        ),
    },
    {
        "id": "11",
        "filename": "11-comprehensive-practice.md",
        "title": "综合实战项目",
        "difficulty": 4,
        "duration": "50-60 分钟",
        "phase": 5,
        "background": (
            "## 实验背景\n\n"
            "前 10 个实验各自聚焦一个知识点。本实验将它们**全部综合运用**，"
            "部署一个接近生产规格的三层 Web 应用。\n\n"
            "### 目标架构\n\n"
            "```\n"
            "Ingress（统一入口）\n"
            "  │\n"
            "  ├─ /       → Frontend Service（3 副本）\n"
            "  └─ /api    → Backend Service（2 副本）\n"
            "                   │\n"
            "               MySQL Service（StatefulSet）\n"
            "                   │\n"
            "               PVC（持久化数据）\n"
            "```\n\n"
            "### 综合运用的知识点\n\n"
            "| 知识点 | 应用场景 |\n"
            "|--------|----------|\n"
            "| Namespace | dev/prod 环境隔离 |\n"
            "| ConfigMap | 应用配置外挂 |\n"
            "| Secret | 数据库密码 |\n"
            "| PVC | 数据库持久化 |\n"
            "| StatefulSet | MySQL 有序管理 |\n"
            "| Ingress | 统一 HTTP 路由 |\n"
            "| NetworkPolicy | 限制 DB 只被后端访问 |\n\n"
            "**完成本实验**，你就具备了在 K8s 上部署真实业务的基础能力。"
        ),
    },
]


@router.get("", summary="List all experiments")
async def list_experiments() -> JSONResponse:
    """
    Return the list of all experiment metadata.
    Fetches from Directus when available; falls back to hardcoded list.

    Returns:
        JSON with experiments array containing id, title, difficulty, duration, phase
    """
    directus_experiments = await fetch_experiment_list()
    if directus_experiments is not None:
        return JSONResponse({"experiments": directus_experiments})
    return JSONResponse({"experiments": EXPERIMENTS})


@router.get("/{exp_id}", summary="Get experiment content")
async def get_experiment(
    exp_id: str,
    session_token: Optional[str] = Cookie(None),
) -> JSONResponse:
    """
    Return the Markdown content of a specific experiment.
    Fetches from Directus when available; falls back to local Markdown file.

    Args:
        exp_id: Two-digit experiment ID, e.g. "01", "11"

    Returns:
        JSON with id, title, difficulty, duration, background, and raw Markdown content
    """
    # Try Directus first
    directus_detail = await fetch_experiment_detail(exp_id)
    if directus_detail is not None:
        if session_token:
            auth_manager.update_session_activity(session_token, current_experiment=exp_id)
        return JSONResponse(directus_detail)

    # Fall back to local hardcoded metadata + Markdown file
    exp = next((e for e in EXPERIMENTS if e["id"] == exp_id), None)
    if not exp:
        raise HTTPException(status_code=404, detail=f"Experiment '{exp_id}' not found")

    file_path = (EXPERIMENTS_DIR / str(exp["filename"])).resolve()
    safe_root = EXPERIMENTS_DIR.resolve()
    if not str(file_path).startswith(str(safe_root) + "/") and file_path != safe_root:
        raise HTTPException(status_code=404, detail=f"Experiment file not found: {exp['filename']}")
    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Experiment file not found: {exp['filename']}"
        )

    content = file_path.read_text(encoding="utf-8")

    if session_token:
        auth_manager.update_session_activity(session_token, current_experiment=exp_id)

    return JSONResponse({
        "id": exp_id,
        "title": exp["title"],
        "difficulty": exp["difficulty"],
        "duration": exp["duration"],
        "background": exp.get("background", ""),
        "content": content,
    })
