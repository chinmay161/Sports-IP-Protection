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

LOCAL_ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
app.mount("/files", StaticFiles(directory=str(LOCAL_ARTIFACT_ROOT)), name="files")



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
