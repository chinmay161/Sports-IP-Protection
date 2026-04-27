# app/main.py
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.storage import LOCAL_ARTIFACT_ROOT
from app.api.alerts import router as alerts_router
from app.api.assets import router as assets_router
from app.api.detections import router as detections_router
from app.api.propagation import router as propagation_router
from app.api.stats import router as stats_router
from app.api.ws import router as ws_router  # NEW
from app.api.live_streams import router as live_streams_router
from app.db.milvus import ensure_collection
from app.db.session import init_db
from app.services.events import close_redis  # NEW
from app.workers.event_subscriber import run_event_subscriber
from app.api.visual import router as visual_router


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

    # NEW: start the Redis -> WebSocket subscriber as a background task.
    subscriber_task = asyncio.create_task(run_event_subscriber(), name="event_subscriber")
    logger.info("event_subscriber_started")

    try:
        yield
    finally:
        # NEW: clean shutdown of subscriber + Redis client.
        subscriber_task.cancel()
        try:
            await subscriber_task
        except asyncio.CancelledError:
            pass
        await close_redis()
        logger.info("event_subscriber_stopped")


app = FastAPI(title="Sports IP Protection API", lifespan=lifespan)
app.include_router(assets_router)
app.include_router(detections_router, prefix="/detections", tags=["detections"])
app.include_router(alerts_router)
app.include_router(propagation_router, prefix="/propagation", tags=["propagation"])
app.include_router(stats_router)
app.include_router(ws_router)  # NEW
app.include_router(visual_router)
app.include_router(live_streams_router, prefix="/live-streams", tags=["live-streams"])

LOCAL_ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
app.mount("/files", StaticFiles(directory=str(LOCAL_ARTIFACT_ROOT)), name="files")


# ---------------------------------------------------------------------------
# Serve the built React frontend in production.
#
# In dev, Vite serves the frontend on :5173 and proxies /api to :8001.
# In production we ship a single container that serves both — frontend
# static files at / and API at /alerts, /detections, etc.
#
# We mount this *last* so the API routes registered above take precedence.
# ---------------------------------------------------------------------------
import os
from pathlib import Path

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

_FRONTEND_DIST = os.getenv("FRONTEND_DIST")
if _FRONTEND_DIST and Path(_FRONTEND_DIST).is_dir():
    _DIST = Path(_FRONTEND_DIST)
    # Vite emits HTML referencing /static/assets/index-XXX.js (because of
    # base: '/static/' + Vite's default output dir 'assets/'). Mount the
    # entire dist directory at /static so that path resolves correctly:
    # URL /static/assets/index-XXX.js -> file dist/assets/index-XXX.js
    app.mount("/static", StaticFiles(directory=_DIST), name="static")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_react_app(full_path: str):
        # Don't shadow API routes — if frontend asks for an API path, return a
        # real 404 instead of index.html. Otherwise frontend code tries to parse
        # HTML as JSON and breaks. This also handles routes defined AFTER this
        # one in the file (Python decorator order matters in FastAPI).
        api_prefixes = (
            "alerts", "detections", "assets", "propagation", "stats", "ws",
            "health", "live-streams", "visual", "files", "static", "openapi.json",
            "docs", "redoc",
        )
        if full_path.startswith(api_prefixes):
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Not found")

        # Serve specific files from dist if they exist (favicon, vite.svg, etc.)
        candidate = _DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        # Otherwise serve index.html — React Router handles client-side routing
        return FileResponse(_DIST / "index.html")


@app.get("/")
async def read_root() -> dict[str, str]:
    return {"message": "FastAPI is running"}


@app.get("/health")
async def health_check() -> dict[str, str | None]:
    return {
        "status": "ok" if app.state.milvus_ready else "degraded",
        "milvus": "ready" if app.state.milvus_ready else "unavailable",
        "milvus_error": app.state.milvus_error,
    }
