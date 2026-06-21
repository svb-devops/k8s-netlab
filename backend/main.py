"""
K8S NetLab - FastAPI Application

Main entry point for the K8S NetLab backend API server.
Provides RESTful endpoints for VM management and WebSocket terminal access.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

# Load environment variables first
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator

from backend import config
from backend.admin_routes import router as admin_router
from backend.api_routes import router as api_router
from backend.auth import auth_manager
from backend.auth_routes import router as auth_router
from backend.ai_tutor_routes import router as ai_tutor_router
from backend.articles_routes import router as articles_router
from backend.deployments_routes import router as deployments_router
from backend.docs_routes import router as docs_router
from backend.labgen.routes import router as labgen_router
from backend.labgen.routes import (
    lab_session_router,
    internal_router,
    verifier_router,
    lab_draft_gen_router,
    learner_catalog_router,
    demo_seed_router,
    image_router,
    rehearsal_router,
)
from backend.labgen.article_draft_routes import router as article_draft_router
from backend.middleware import JsonFormatter, RequestIDMiddleware, SecurityHeadersMiddleware
from backend.proxmox_api import connect_proxmox
from backend.task_registry import drain as drain_vm_tasks
from backend.vm_manager import delete_vm
from backend.vm_tracker import vm_tracker

# Configure structured JSON logging
_handler = logging.StreamHandler()
_handler.setFormatter(JsonFormatter())
logging.root.handlers = [_handler]
logging.root.setLevel(getattr(logging, config.LOG_LEVEL))
logger = logging.getLogger(__name__)


# ============================================================
# Background Tasks
# ============================================================

async def auto_cleanup_task():
    """
    Background task to automatically delete expired VMs.

    Runs every minute and deletes VMs older than 30 minutes.
    """
    logger.info("Auto-cleanup task started (checking every 60 seconds)")

    while True:
        try:
            await asyncio.sleep(60)  # Check every minute

            # Purge expired sessions from sessions.json
            auth_manager.cleanup_expired_sessions()

            # Get expired VMs (older than config.VM_SESSION_TIMEOUT_MIN minutes)
            expired_vms = vm_tracker.get_expired_vms(max_age_minutes=config.VM_SESSION_TIMEOUT_MIN)

            if expired_vms:
                logger.info(f"Found {len(expired_vms)} expired VMs to delete: {expired_vms}")

                for vm_id in expired_vms:
                    try:
                        # Skip template VM and exempt platform/staging VMs.
                        # Exempt VMs are NOT untracked so ownership checks remain valid.
                        if vm_id == config.VM_TEMPLATE_ID:
                            logger.info(f"Auto-cleanup: Skipping template VM {vm_id}")
                            vm_tracker.untrack_vm(vm_id)
                            continue
                        if vm_id in config.VM_CLEANUP_EXEMPT_IDS:
                            logger.info(f"Auto-cleanup: Skipping exempt VM {vm_id} (platform/staging)")
                            continue

                        logger.info(f"Auto-cleanup: Deleting expired VM {vm_id}")
                        loop = asyncio.get_running_loop()
                        result = await loop.run_in_executor(
                            None, lambda: delete_vm(vm_id=vm_id, force=True)
                        )

                        if result['success']:
                            logger.info(f"Auto-cleanup: VM {vm_id} deleted successfully")
                            vm_tracker.untrack_vm(vm_id)
                        else:
                            error = result['error'] or ""
                            # VM no longer exists in Proxmox — stop tracking it
                            if "does not exist" in error or "Configuration file" in error:
                                logger.warning(f"Auto-cleanup: VM {vm_id} not found in Proxmox (reason: {error!r}), removing from tracker")
                                vm_tracker.untrack_vm(vm_id)
                            else:
                                logger.error(f"Auto-cleanup: Failed to delete VM {vm_id}: {error}")

                    except asyncio.CancelledError:
                        logger.info(f"Auto-cleanup: Cancelled while deleting VM {vm_id}")
                        raise
                    except Exception as e:
                        logger.error(f"Auto-cleanup: Error deleting VM {vm_id}: {e}")

        except asyncio.CancelledError:
            logger.info("Auto-cleanup task cancelled")
            break
        except Exception as e:
            logger.error(f"Auto-cleanup task error: {e}")
            # Continue running even if there's an error


# ============================================================
# Application Lifecycle
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan context manager.

    Handles startup and shutdown logic:
    - Startup: Test Proxmox connection
    - Shutdown: Cleanup resources
    """
    # Startup
    logger.info("=" * 60)
    logger.info("K8S NetLab - Starting up...")
    logger.info("=" * 60)

    try:
        # Test Proxmox connection
        logger.info("Testing Proxmox connection...")
        proxmox = connect_proxmox()
        version_info = proxmox.version.get()

        auth_label = (
            f"token ({config.PROXMOX_TOKEN_ID})"
            if config._proxmox_auth_method == "token"
            else f"password ({config.PROXMOX_USER})"
        )
        logger.info(f"✓ Connected to Proxmox VE {version_info.get('version')}")
        logger.info(f"  Host: {config.PROXMOX_HOST}:{config.PROXMOX_PORT}")
        logger.info(f"  Node: {config.PROXMOX_NODE}")
        logger.info(f"  Auth: {auth_label}")

    except Exception as e:
        logger.error(f"✗ Proxmox connection failed: {e}")
        logger.error("Application will start but may not function correctly")

    logger.info("")
    logger.info(f"API listening on http://{config.APP_HOST}:{config.APP_PORT}")
    logger.info(f"Debug mode: {config.APP_DEBUG}")
    logger.info("=" * 60)

    # Start background auto-cleanup task
    cleanup_task = asyncio.create_task(auto_cleanup_task())
    logger.info("Background auto-cleanup task started")

    yield

    # Shutdown
    logger.info("=" * 60)
    logger.info("K8S NetLab - Shutting down...")
    logger.info("=" * 60)

    # Wait for in-flight VM operations (create/delete) before exiting
    await drain_vm_tasks(timeout=30.0)

    # Cancel background task
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        logger.info("Auto-cleanup task stopped")



# ============================================================
# Create FastAPI Application
# ============================================================

app = FastAPI(
    title="K8S NetLab API",
    description="RESTful API for managing Kubernetes learning lab VMs",
    version="1.1.0",
    lifespan=lifespan,
    debug=config.APP_DEBUG
)

# ============================================================
# CORS Middleware
# ============================================================
# Only mount when ALLOWED_ORIGINS is explicitly configured.
# When empty (default), no CORS headers are sent and all
# cross-origin requests are rejected — the safest default.

app.add_middleware(RequestIDMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# Prometheus metrics — exposed at /metrics (scrape target for Prometheus/Grafana)
Instrumentator().instrument(app).expose(app, endpoint="/metrics")

if config.ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Cookie"],
    )
    logger.info(f"CORS middleware enabled for: {config.ALLOWED_ORIGINS}")
else:
    logger.warning("CORS middleware NOT loaded — cross-origin requests blocked")

# ============================================================
# Include Routers
# ============================================================

app.include_router(auth_router)      # Authentication routes
app.include_router(api_router)       # VM management routes
app.include_router(docs_router)      # Experiment documentation routes
app.include_router(deployments_router) # Deployment cases routes
app.include_router(ai_tutor_router)  # AI tutor chat routes
app.include_router(admin_router)     # Admin observability routes
app.include_router(articles_router)  # Public blog articles
app.include_router(labgen_router)         # LabGen draft management
app.include_router(lab_session_router)    # Lab session lifecycle
app.include_router(internal_router)       # Internal cleanup (admin only)
app.include_router(verifier_router)       # Internal verifier check (admin only)
app.include_router(lab_draft_gen_router)  # LLM draft generation
app.include_router(learner_catalog_router)  # Learner lab catalog & eligibility
app.include_router(demo_seed_router)       # Demo seed (dev/demo only, admin-gated)
app.include_router(image_router)           # Image resolve & existence check
app.include_router(rehearsal_router)       # Internal rehearsal bridge (admin only, X-Admin-Token)
app.include_router(article_draft_router)   # Article-to-Lab draft pipeline (admin only)


# ============================================================
# WebSocket Routes
# ============================================================

from backend.websocket import websocket_terminal
from backend.labgen.lab_kubectl_ws import lab_kubectl_websocket
from backend.labgen.routes import get_session_repository


@app.websocket("/ws/lab-kubectl/{session_id}")
async def lab_kubectl_endpoint(websocket: WebSocket, session_id: str):
    """
    WebSocket kubectl terminal for an active LabGen lab session.

    Security layers:
    1. Requires session_token cookie (same auth as /ws/terminal).
    2. Session must exist and be owned by the authenticated user.
    3. Session must be in LAB_ACTIVE state.
    4. Commands are validated by kubectl_executor before execution.
    5. Session state is polled every 10s; connection closes if session ends.
    """
    await lab_kubectl_websocket(websocket, session_id, get_session_repository())


@app.websocket("/ws/terminal/{vm_id}")
async def terminal_endpoint(websocket: WebSocket, vm_id: int):
    """
    WebSocket terminal endpoint with authentication and ownership checks.

    Security layers:
    1. Session token must be present in cookies
    2. Session token must be valid and not expired
    3. Requesting user must own the target VM

    Args:
        websocket: WebSocket connection
        vm_id: VM ID to connect to
    """
    await websocket.accept()

    # --- Layer 1: Require session token ---
    session_token = websocket.cookies.get("session_token")
    if not session_token:
        logger.warning(
            f"WebSocket terminal rejected: no session_token cookie "
            f"(vm_id={vm_id}, client={websocket.client})"
        )
        await websocket.send_json({
            "type": "error",
            "message": "未登录，请先登录后再使用终端"
        })
        await websocket.close(code=1008)  # 1008 = Policy Violation
        return

    # --- Layer 2: Verify session is valid ---
    username = auth_manager.verify_session(session_token)
    if not username:
        logger.warning(
            f"WebSocket terminal rejected: invalid/expired session "
            f"(vm_id={vm_id}, client={websocket.client})"
        )
        await websocket.send_json({
            "type": "error",
            "message": "登录已过期，请重新登录"
        })
        await websocket.close(code=1008)
        return

    # --- Layer 3: Verify VM ownership ---
    vm_owner = vm_tracker.get_vm_owner(vm_id)
    if vm_owner is None:
        logger.warning(
            f"WebSocket terminal rejected: VM {vm_id} not found in tracker "
            f"(user={username}, client={websocket.client})"
        )
        await websocket.send_json({
            "type": "error",
            "message": f"VM {vm_id} 不存在或已被删除"
        })
        await websocket.close(code=1008)
        return

    if not vm_tracker.is_owner(vm_id, username):
        logger.warning(
            f"WebSocket terminal rejected: ownership check failed "
            f"(vm_id={vm_id}, requesting_user={username}, owner={vm_owner}, "
            f"client={websocket.client})"
        )
        await websocket.send_json({
            "type": "error",
            "message": "您无权访问此 VM 的终端"
        })
        await websocket.close(code=1008)
        return

    # --- All checks passed ---
    logger.info(
        f"WebSocket terminal authorized: user={username}, vm_id={vm_id}, "
        f"client={websocket.client}"
    )
    # Skip K3s readiness wait for mature VMs — K3s is already running on reconnect
    skip_k3s = vm_tracker.get_vm_age_minutes(vm_id) > 5
    await websocket_terminal(websocket, vm_id, skip_k3s_wait=skip_k3s)


# ============================================================
# Static Files
# ============================================================

# Get project root directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"

class NoCacheStaticFiles(StaticFiles):
    """StaticFiles that forbids long-lived edge/browser caching.

    Cloudflare honors the origin's Cache-Control header (Origin Cache
    Control). The default starlette StaticFiles response has no
    Cache-Control header, which Cloudflare was treating as cacheable for
    its default TTL (~4h) — so a JS bugfix deployed to disk could stay
    invisible to real users for hours. Force revalidation on every request.
    """

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


# Mount static files (JS, CSS)
app.mount("/js", NoCacheStaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")
app.mount("/css", NoCacheStaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")


# ============================================================
# Root Endpoints
# ============================================================

@app.get(
    "/",
    summary="Landing Page",
    description="Serve the public landing page (articles list)",
    include_in_schema=False
)
async def root():
    from fastapi.responses import FileResponse
    return FileResponse(str(FRONTEND_DIR / "landing.html"))


@app.get(
    "/app",
    summary="Web UI",
    description="Serve the main app (login required)",
    include_in_schema=False
)
async def app_page():
    from fastapi.responses import FileResponse
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get(
    "/article.html",
    summary="Article Detail",
    description="Serve the article detail page",
    include_in_schema=False
)
async def article_page():
    from fastapi.responses import FileResponse
    return FileResponse(str(FRONTEND_DIR / "article.html"))


@app.get(
    "/login.html",
    summary="Login Page",
    description="Serve the login page",
    include_in_schema=False
)
async def login_page():
    """
    Serve the login page.

    Returns:
        HTML: The login page
    """
    from fastapi.responses import FileResponse
    return FileResponse(str(FRONTEND_DIR / "login.html"))


@app.get(
    "/admin.html",
    summary="Admin Console",
    description="Serve the admin observability console",
    include_in_schema=False
)
async def admin_page():
    """
    Serve the admin console page.

    Token verification happens client-side via X-Admin-Token header.

    Returns:
        HTML: The admin console
    """
    from fastapi.responses import FileResponse
    return FileResponse(str(FRONTEND_DIR / "admin.html"))


@app.get("/labgen-admin.html", include_in_schema=False)
async def labgen_admin_page():
    from fastapi.responses import FileResponse
    return FileResponse(str(FRONTEND_DIR / "labgen-admin.html"))


@app.get("/labgen-catalog.html", include_in_schema=False)
async def labgen_catalog_page():
    from fastapi.responses import FileResponse
    return FileResponse(str(FRONTEND_DIR / "labgen-catalog.html"))


@app.get("/labgen-lab.html", include_in_schema=False)
async def labgen_lab_page():
    from fastapi.responses import FileResponse
    return FileResponse(str(FRONTEND_DIR / "labgen-lab.html"))


@app.get("/labgen-session.html", include_in_schema=False)
async def labgen_session_page():
    from fastapi.responses import FileResponse
    return FileResponse(str(FRONTEND_DIR / "labgen-session.html"))


@app.get("/labgen-dev.html", include_in_schema=False)
async def labgen_dev_page():
    from fastapi.responses import FileResponse
    return FileResponse(str(FRONTEND_DIR / "labgen-dev.html"))


@app.get(
    "/api",
    summary="API Information",
    description="Get API version and available endpoints"
)
async def api_info() -> JSONResponse:
    """
    API information endpoint.

    Returns:
        dict: API version and endpoints
    """
    return JSONResponse({
        "endpoints": {
            "vms": {
                "list": "GET /api/vms",
                "create": "POST /api/vms/create",
                "delete": "DELETE /api/vms/{vm_id}",
                "status": "GET /api/vms/{vm_id}/status"
            },
            "health": "GET /api/health"
        }
    })


# ============================================================
# Error Handlers
# ============================================================

@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception) -> JSONResponse:
    """
    Global exception handler for unhandled errors.

    Args:
        request: The request that caused the exception
        exc: The exception that was raised

    Returns:
        JSONResponse with error details
    """
    logger.error(f"Unhandled exception: {exc}", exc_info=True)

    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "Internal server error",
            "detail": str(exc) if config.APP_DEBUG else "An unexpected error occurred"
        }
    )


# ============================================================
# Main Entry Point
# ============================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=config.APP_HOST,
        port=config.APP_PORT,
        reload=config.APP_DEBUG,
        log_level=config.LOG_LEVEL.lower()
    )
