import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.core.config import settings
from backend.core.database import init_db
from backend.routers import auth, connections, settings as settings_router, dashboard, jobs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("imnid.backend")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing IMNID Hub database and storage directories...")
    # Ensure all data directories exist
    _ = settings.uploads_dir
    _ = settings.exports_dir
    _ = settings.logs_dir
    _ = settings.checkpoints_dir
    _ = settings.db_path
    init_db()
    logger.info("IMNID Hub backend initialized successfully.")
    yield

app = FastAPI(
    title="IMNID Hub API",
    version="1.0.0",
    description="Unified Backend API for IMNID Hub data interoperability and health information management.",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error on {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)}
    )

@app.get("/api/health", tags=["System"])
def health_check():
    return {
        "status": "healthy",
        "service": "IMNID Hub Backend",
        "version": "1.0.0",
        "app_env": settings.APP_ENV
    }

from backend.modules.smartcare import router as smartcare_router
from backend.modules.data_management import router as data_management_router
from backend.modules.interop import router as interop_router
from backend.modules.concepts import router as concepts_router
from backend.modules.hmis import router as hmis_router
from fastapi.staticfiles import StaticFiles
from pathlib import Path

# Mount core routers
app.include_router(auth.router)
app.include_router(connections.router)
app.include_router(settings_router.router)
app.include_router(dashboard.router)
app.include_router(jobs.router)
app.include_router(smartcare_router.router)
app.include_router(data_management_router.router)
app.include_router(interop_router.router)
app.include_router(concepts_router.router)
app.include_router(hmis_router.router)

# Mount static frontend if available (for native desktop / standalone installations)
def setup_frontend_serving(application: FastAPI):
    import sys
    candidates = []
    if getattr(sys, "frozen", False):
        base_dir = Path(getattr(sys, "_MEIPASS", ""))
        candidates.append(base_dir / "frontend" / "dist")
        candidates.append(base_dir / "dist")
    candidates.extend([
        Path(__file__).resolve().parent.parent / "frontend" / "dist",
        Path.cwd() / "frontend" / "dist",
        Path.cwd() / "dist",
        Path(__file__).resolve().parent / "dist",
    ])
    dist_dir = None
    for cand in candidates:
        if cand.is_dir() and (cand / "index.html").is_file():
            dist_dir = cand
            break

    if dist_dir:
        assets_dir = dist_dir / "assets"
        if assets_dir.is_dir():
            application.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend_assets")

        @application.get("/{full_path:path}", include_in_schema=False)
        async def serve_frontend(request: Request, full_path: str):
            if full_path.startswith("api/") or full_path in ("api", "docs", "redoc", "openapi.json"):
                return JSONResponse(status_code=404, content={"detail": "Not found"})
            file_path = dist_dir / full_path
            if file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(dist_dir / "index.html")

setup_frontend_serving(app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.BACKEND_PORT)
