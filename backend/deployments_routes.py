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
    },
    {
        "id": "D02",
        "filename": "D02-wordpress-mysql.md",
        "title": "有状态应用：MySQL + 持久化存储",
        "difficulty": 4,
        "duration": "45 分钟",
        "phase": 2,
    },
    {
        "id": "D03",
        "filename": "D03-blue-green-deploy.md",
        "title": "蓝绿部署与滚动更新",
        "difficulty": 3,
        "duration": "35 分钟",
        "phase": 1,
    },
    {
        "id": "D04",
        "filename": "D04-cronjob.md",
        "title": "CronJob 定时任务系统",
        "difficulty": 3,
        "duration": "30 分钟",
        "phase": 2,
    },
    {
        "id": "D05",
        "filename": "D05-multi-namespace.md",
        "title": "多命名空间微服务隔离",
        "difficulty": 4,
        "duration": "40 分钟",
        "phase": 3,
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
        "content": content,
    })
