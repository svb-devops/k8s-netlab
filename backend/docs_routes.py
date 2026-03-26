"""
K8S NetLab - Experiment Documentation API Routes

Provides endpoints to list and serve Markdown experiment documents.
"""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Cookie, HTTPException
from fastapi.responses import JSONResponse

from backend.auth import auth_manager

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
    },
    {
        "id": "02",
        "filename": "02-pod-network-deep-dive.md",
        "title": "Pod 网络深入探索",
        "difficulty": 3,
        "duration": "35-40 分钟",
        "phase": 1,
    },
    {
        "id": "03",
        "filename": "03-service-loadbalancing.md",
        "title": "Service 负载均衡",
        "difficulty": 3,
        "duration": "35-40 分钟",
        "phase": 1,
    },
    {
        "id": "04",
        "filename": "04-ingress-controller.md",
        "title": "Ingress 控制器详解",
        "difficulty": 4,
        "duration": "45-50 分钟",
        "phase": 2,
    },
    {
        "id": "05",
        "filename": "05-network-policy.md",
        "title": "NetworkPolicy 网络策略",
        "difficulty": 3,
        "duration": "35-40 分钟",
        "phase": 2,
    },
    {
        "id": "06",
        "filename": "06-dns-service-discovery.md",
        "title": "DNS 服务发现",
        "difficulty": 3,
        "duration": "35-40 分钟",
        "phase": 2,
    },
    {
        "id": "07",
        "filename": "07-persistent-storage.md",
        "title": "持久化存储 PV/PVC",
        "difficulty": 3,
        "duration": "40-45 分钟",
        "phase": 3,
    },
    {
        "id": "08",
        "filename": "08-configmap-secret.md",
        "title": "ConfigMap 和 Secret",
        "difficulty": 3,
        "duration": "35-40 分钟",
        "phase": 3,
    },
    {
        "id": "09",
        "filename": "09-statefulset.md",
        "title": "StatefulSet 有状态应用",
        "difficulty": 4,
        "duration": "45-50 分钟",
        "phase": 4,
    },
    {
        "id": "10",
        "filename": "10-monitoring-logging.md",
        "title": "监控和日志管理",
        "difficulty": 3,
        "duration": "35-40 分钟",
        "phase": 4,
    },
    {
        "id": "11",
        "filename": "11-comprehensive-practice.md",
        "title": "综合实战项目",
        "difficulty": 4,
        "duration": "50-60 分钟",
        "phase": 5,
    },
]


@router.get("", summary="List all experiments")
async def list_experiments() -> JSONResponse:
    """
    Return the list of all experiment metadata.

    Returns:
        JSON with experiments array containing id, title, difficulty, duration, phase
    """
    return JSONResponse({"experiments": EXPERIMENTS})


@router.get("/{exp_id}", summary="Get experiment content")
async def get_experiment(
    exp_id: str,
    session_token: Optional[str] = Cookie(None),
) -> JSONResponse:
    """
    Return the Markdown content of a specific experiment.

    Args:
        exp_id: Two-digit experiment ID, e.g. "01", "11"

    Returns:
        JSON with id, title, and raw Markdown content string
    """
    exp = next((e for e in EXPERIMENTS if e["id"] == exp_id), None)
    if not exp:
        raise HTTPException(status_code=404, detail=f"Experiment '{exp_id}' not found")

    file_path = EXPERIMENTS_DIR / str(exp["filename"])
    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Experiment file not found: {exp['filename']}"
        )

    content = file_path.read_text(encoding="utf-8")

    # Record current experiment for admin observability (best-effort, never blocks response)
    if session_token:
        auth_manager.update_session_activity(session_token, current_experiment=exp_id)

    return JSONResponse({
        "id": exp_id,
        "title": exp["title"],
        "difficulty": exp["difficulty"],
        "duration": exp["duration"],
        "content": content,
    })
