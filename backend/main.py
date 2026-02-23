"""
K8S NetLab - FastAPI Application

Main entry point for the K8S NetLab backend API server.
Provides RESTful endpoints for VM management and WebSocket terminal access.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from pathlib import Path

# Load environment variables first
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend import config
from backend.api_routes import router as api_router
from backend.auth_routes import router as auth_router
from backend.docs_routes import router as docs_router
from backend.proxmox_api import connect_proxmox
from backend.vm_tracker import vm_tracker
from backend.vm_manager import delete_vm

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
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

            # Get expired VMs (older than 30 minutes)
            expired_vms = vm_tracker.get_expired_vms(max_age_minutes=30)

            if expired_vms:
                logger.info(f"Found {len(expired_vms)} expired VMs to delete: {expired_vms}")

                for vm_id in expired_vms:
                    try:
                        # Skip template VMs (ID 100 is the template)
                        if vm_id == 100:
                            logger.info(f"Auto-cleanup: Skipping template VM {vm_id}")
                            vm_tracker.untrack_vm(vm_id)  # Remove from tracking
                            continue

                        logger.info(f"Auto-cleanup: Deleting expired VM {vm_id}")
                        result = delete_vm(vm_id=vm_id, force=True)

                        if result['success']:
                            logger.info(f"Auto-cleanup: VM {vm_id} deleted successfully")
                            vm_tracker.untrack_vm(vm_id)
                        else:
                            logger.error(f"Auto-cleanup: Failed to delete VM {vm_id}: {result['error']}")

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

        logger.info(f"✓ Connected to Proxmox VE {version_info.get('version')}")
        logger.info(f"  Host: {config.PROXMOX_HOST}:{config.PROXMOX_PORT}")
        logger.info(f"  Node: {config.PROXMOX_NODE}")
        logger.info(f"  User: {config.PROXMOX_USER}")

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
    version="0.1.0",
    lifespan=lifespan,
    debug=config.APP_DEBUG
)

# ============================================================
# CORS Middleware
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",  # Echo specific origin (required when allow_credentials=True)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# Include Routers
# ============================================================

app.include_router(auth_router)  # Authentication routes
app.include_router(api_router)   # VM management routes
app.include_router(docs_router)  # Experiment documentation routes


# ============================================================
# WebSocket Routes
# ============================================================

from backend.websocket import websocket_terminal


@app.websocket("/ws/terminal/{vm_id}")
async def terminal_endpoint(websocket: WebSocket, vm_id: int):
    """
    WebSocket terminal endpoint.

    Args:
        websocket: WebSocket connection
        vm_id: VM ID to connect to
    """
    await websocket_terminal(websocket, vm_id)


# ============================================================
# Static Files
# ============================================================

# Get project root directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"

# Mount static files (JS, CSS)
app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")
app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")


# ============================================================
# Root Endpoints
# ============================================================

@app.get(
    "/",
    summary="Web UI",
    description="Serve the web interface",
    include_in_schema=False
)
async def root():
    """
    Serve the main web interface.

    Returns:
        HTML: The K8S NetLab web UI
    """
    from fastapi.responses import FileResponse
    return FileResponse(str(FRONTEND_DIR / "index.html"))


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
        "version": "0.1.0",
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
