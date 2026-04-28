# app/main.py
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.storage import LOCAL_ARTIFACT_ROOT
from app.api.alerts import router as alerts_router
from app.api.assets import router as assets_router
from app.api.detections import router as detections_router
from app.api.propagation import router as propagation_router
from app.api.stats import router as stats_router
from app.api.ws import router as ws_router
from app.api.live_streams import router as live_streams_router
from app.api.visual import router as visual_router
from app.db.milvus import ensure_collection
from app.db.session import init_db
from app.services.events import close_redis
from app.workers.event_subscriber import run_event_subscriber


logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.milvus_ready = False
    app.state.milvus_error = None

    await init_db()

    try:
        await ensure_collection()
        app.state.milvus_ready = True
    except Exception as exc:
        app.state.milvus_error = str(exc)
        if settings.milvus_required:
            raise
        logger.warning("milvus_startup_unavailable error=%s", exc)

    subscriber_task = asyncio.create_task(run_event_subscriber(), name="event_subscriber")
    logger.info("event_subscriber_started")

    try:
        yield
    finally:
        subscriber_task.cancel()
        try:
            await subscriber_task
        except asyncio.CancelledError:
            pass
        await close_redis()
        logger.info("event_subscriber_stopped")


app = FastAPI(title="Sports IP Protection API", lifespan=lifespan)

# API routers
app.include_router(assets_router)
app.include_router(detections_router, prefix="/detections", tags=["detections"])
app.include_router(alerts_router)
app.include_router(propagation_router, prefix="/propagation", tags=["propagation"])
app.include_router(stats_router)
app.include_router(ws_router)
app.include_router(visual_router)
app.include_router(live_streams_router, prefix="/live-streams", tags=["live-streams"])

# Local file serving (uploaded artifacts)
LOCAL_ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
app.mount("/files", StaticFiles(directory=str(LOCAL_ARTIFACT_ROOT)), name="files")


# ---------------------------------------------------------------------------
# Health check endpoints — defined BEFORE the React catch-all so FastAPI
# matches these first. /health is required for Render's health checks.
# ---------------------------------------------------------------------------
@app.get("/")
async def read_root() -> dict[str, str]:
    return {"service": "Sports IP Protection API", "status": "ok"}


@app.get("/health")
async def health_check() -> dict[str, str | None]:
    return {
        "status": "ok",
        "service": "sports-ip-protection",
        "milvus_ready": str(getattr(app.state, "milvus_ready", False)),
        "milvus_error": getattr(app.state, "milvus_error", None),
    }


# ---------------------------------------------------------------------------
# Serve the built React frontend in production.
#
# In dev, Vite serves the frontend on :5173 and proxies /api to :8001.
# In production we ship a single container that serves both — frontend
# static files at /static and React app at all other paths. The catch-all
# below MUST be the last route registered.
# ---------------------------------------------------------------------------
_FRONTEND_DIST = os.getenv("FRONTEND_DIST")

if _FRONTEND_DIST and Path(_FRONTEND_DIST).is_dir():
    _DIST = Path(_FRONTEND_DIST)

    # Serve Vite's bundled assets at /static/assets/...
    app.mount("/static", StaticFiles(directory=_DIST), name="static")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_react_app(full_path: str):
        # Block known API prefixes from falling back to index.html, so that
        # frontend code parsing the response as JSON gets a real 404 instead
        # of HTML.
        api_prefixes = (
            "alerts", "detections", "assets", "propagation", "stats", "ws",
            "health", "live-streams", "visual", "files", "openapi.json",
            "docs", "redoc",
        )
        if full_path.startswith(api_prefixes):
            raise HTTPException(status_code=404, detail="Not found")

        # Try serving a specific file from dist (favicon, manifest, etc.)
        candidate = _DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)

        # Fallback: serve index.html so React Router handles client routes
        return FileResponse(_DIST / "index.html")