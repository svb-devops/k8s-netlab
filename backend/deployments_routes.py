"""
K8S NetLab - Deployment Cases API Routes

Provides endpoints to list and serve Markdown deployment case documents.
"""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Cookie
from fastapi.responses import JSONResponse

from backend.auth import auth_manager

router = APIRouter(prefix="/api/deployments", tags=["deployments"])

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEPLOYMENTS_DIR = PROJECT_ROOT / "docs" / "deployments"

DEPLOYMENT_CASES = [
    {
        "id": "D01",
        "filename": "D01-guestbook.md",
        "title": "留言板应用（Guestbook）",
        "difficulty": 3,
        "duration": "30 分钟",
        "phase": 1,
        "background": (
            "## 案例背景\n\n"
            "Guestbook 是 Kubernetes 官方入门示例，展示**多层微服务架构**在 K8s 上的运行方式。\n\n"
            "### 架构要点\n\n"
            "应用由三层构成：\n\n"
            "- **PHP 前端**（3 副本）：接收用户请求，读写留言\n"
            "- **Redis Leader**（1 副本）：处理所有**写操作**\n"
            "- **Redis Follower**（2 副本）：处理所有**读操作**，与 Leader 实时同步\n\n"
            "### 核心概念\n\n"
            "| 概念 | 作用 |\n"
            "|------|------|\n"
            "| Deployment | 声明式管理 Pod 副本数 |\n"
            "| Service (ClusterIP) | 内部服务发现，通过 DNS 名称访问 |\n"
            "| Service (LoadBalancer) | 对外暴露前端入口 |\n"
            "| 读写分离 | Leader 写、Follower 读，提升吞吐量 |\n\n"
            "### 为什么这样设计？\n\n"
            "前端通过 `GET_HOSTS_FROM=dns` 环境变量，在运行时动态从 DNS "
            "解析 `redis-leader` / `redis-follower` 地址，**不硬编码 IP**。"
            "这正是 Kubernetes Service 抽象的核心价值。"
        ),
    },
    {
        "id": "D02",
        "filename": "D02-wordpress-mysql.md",
        "title": "有状态应用：MySQL + 持久化存储",
        "difficulty": 4,
        "duration": "45 分钟",
        "phase": 2,
        "background": (
            "## 案例背景\n\n"
            "MySQL 是典型的**有状态应用**，它与无状态服务有根本区别：\n"
            "数据不能随 Pod 消失而消失。\n\n"
            "### 核心挑战\n\n"
            "1. **数据持久化**：Pod 重启后数据必须保留 → 需要 PersistentVolume\n"
            "2. **稳定 DNS**：应用需要固定地址连接数据库 → 需要 Headless Service\n"
            "3. **避免数据损坏**：多个 Pod 同时挂载同一卷会导致数据库崩溃 → 需要 Recreate 策略\n\n"
            "### 关键 K8s 对象\n\n"
            "| 对象 | 用途 |\n"
            "|------|------|\n"
            "| PersistentVolume (PV) | 宿主机磁盘上的实际存储空间 |\n"
            "| PersistentVolumeClaim (PVC) | Pod 申请存储的凭证 |\n"
            "| Headless Service | `clusterIP: None`，直接返回 Pod IP |\n"
            "| Recreate 策略 | 先删旧 Pod 再建新 Pod，防止 PVC 竞争 |\n\n"
            "### 有状态 vs 无状态\n\n"
            "无状态应用（如前端、API）可随意扩缩容；有状态应用（如数据库）"
            "扩容往往需要特殊协议（主从复制、选主等），本案例演示最基础的单实例有状态场景。"
        ),
    },
    {
        "id": "D03",
        "filename": "D03-blue-green-deploy.md",
        "title": "蓝绿部署与滚动更新",
        "difficulty": 3,
        "duration": "35 分钟",
        "phase": 1,
        "background": (
            "## 案例背景\n\n"
            "生产发布的核心诉求是**零停机**。K8s 提供两种主流发布策略：\n\n"
            "### 蓝绿部署\n\n"
            "同时运行两套完整环境（蓝=当前版本，绿=新版本），"
            "通过切换 Service selector 实现**秒级流量切换**，回滚同样是秒级。\n\n"
            "- **优点**：切换即时，回滚零风险\n"
            "- **代价**：需要双倍资源\n\n"
            "### 滚动更新\n\n"
            "逐步用新 Pod 替换旧 Pod，同一时刻两个版本并行运行。\n\n"
            "- **优点**：资源效率高，K8s 原生支持\n"
            "- **代价**：需要前后端兼容，回滚略慢\n\n"
            "### 关键参数\n\n"
            "| 参数 | 含义 |\n"
            "|------|------|\n"
            "| `maxSurge` | 更新期间最多额外创建几个 Pod |\n"
            "| `maxUnavailable` | 更新期间最多有几个 Pod 不可用 |\n\n"
            "两种策略在不同场景下各有优势，了解权衡是高级工程师的必备技能。"
        ),
    },
    {
        "id": "D04",
        "filename": "D04-cronjob.md",
        "title": "CronJob 定时任务系统",
        "difficulty": 3,
        "duration": "30 分钟",
        "phase": 2,
        "background": (
            "## 案例背景\n\n"
            "定时任务是生产系统的常见需求：数据备份、报表生成、日志清理……\n"
            "Kubernetes 用 **CronJob** 原生支持此场景。\n\n"
            "### 三层层级关系\n\n"
            "```\n"
            "CronJob  →（按计划触发）→  Job  →（创建）→  Pod\n"
            "```\n\n"
            "- **CronJob**：维护计划表，每次触发时创建一个 Job\n"
            "- **Job**：确保 Pod 运行直到**成功完成**（不是一直运行）\n"
            "- **Pod**：实际执行任务的容器，完成后状态变为 `Completed`\n\n"
            "### Cron 表达式\n\n"
            "与 Linux crontab 完全一致：`分 时 日 月 周`\n\n"
            "| 表达式 | 含义 |\n"
            "|--------|------|\n"
            "| `* * * * *` | 每分钟 |\n"
            "| `0 * * * *` | 每小时整点 |\n"
            "| `0 2 * * *` | 每天凌晨 2 点 |\n"
            "| `*/5 * * * *` | 每 5 分钟 |\n\n"
            "### restartPolicy\n\n"
            "`OnFailure`：任务失败时重新启动 Pod，直到成功——"
            "这与长期运行的 Deployment（`Always`）完全不同。"
        ),
    },
    {
        "id": "D05",
        "filename": "D05-multi-namespace.md",
        "title": "多命名空间微服务隔离",
        "difficulty": 4,
        "duration": "40 分钟",
        "phase": 3,
        "background": (
            "## 案例背景\n\n"
            "在真实企业中，同一个 K8s 集群往往承载多个团队、多个环境（dev/staging/prod）。\n"
            "**Namespace** 是 K8s 的逻辑隔离机制。\n\n"
            "### Namespace 的作用\n\n"
            "- 同名资源在不同 Namespace 中**互不干扰**\n"
            "- 可以针对 Namespace 设置资源配额（ResourceQuota）\n"
            "- RBAC 权限可以限定在 Namespace 范围\n"
            "- 不同团队的 Pod 默认网络互通（需要 NetworkPolicy 进一步隔离）\n\n"
            "### kubectl context\n\n"
            "Context = 集群 + 用户 + 命名空间的三元组。\n"
            "切换 context 就切换「工作视野」，命令默认只看当前 Namespace 的资源。\n\n"
            "### 本案例演示\n\n"
            "| Namespace | 应用 | 副本数 |\n"
            "|-----------|------|--------|\n"
            "| development | snowflake | 2 |\n"
            "| production | cattle | 5 |\n\n"
            "同名 `snowflake` Deployment 在两个 Namespace 中独立存在，"
            "这正是微服务多租户隔离的基础模式。"
        ),
    },
]


@router.get("", summary="List all deployment cases")
async def list_deployments() -> JSONResponse:
    """Return the list of all deployment case metadata."""
    return JSONResponse({"deployments": DEPLOYMENT_CASES})


@router.get("/{case_id}", summary="Get deployment case content")
async def get_deployment(
    case_id: str,
    session_token: Optional[str] = Cookie(None),
) -> JSONResponse:
    """Return the Markdown content of a specific deployment case."""
    if len(case_id) > 20:
        return JSONResponse({"error": "Invalid case ID"}, status_code=404)

    case = next((c for c in DEPLOYMENT_CASES if c["id"] == case_id), None)
    if not case:
        return JSONResponse({"error": "Deployment case not found"}, status_code=404)

    file_path = (DEPLOYMENTS_DIR / case["filename"]).resolve()
    safe_root = DEPLOYMENTS_DIR.resolve()
    if not str(file_path).startswith(str(safe_root) + "/") and file_path != safe_root:
        return JSONResponse({"error": "File not found"}, status_code=404)

    if not file_path.exists():
        return JSONResponse(
            {"error": f"Deployment case file not found: {case['filename']}"},
            status_code=404,
        )

    content = file_path.read_text(encoding="utf-8")

    if session_token:
        try:
            auth_manager.update_session_activity(session_token, current_experiment=case_id)
        except Exception:
            pass

    return JSONResponse({
        "id": case_id,
        "title": case["title"],
        "difficulty": case["difficulty"],
        "duration": case["duration"],
        "background": case.get("background", ""),
        "content": content,
    })
