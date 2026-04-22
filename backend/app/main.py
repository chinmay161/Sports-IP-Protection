# app/main.py
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.api.assets import router as assets_router
from app.api.alerts import router as alerts_router
from app.db.milvus import ensure_collection
from app.db.session import init_db

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

    yield


app = FastAPI(title="Sports IP Protection API", lifespan=lifespan)
app.include_router(assets_router)
app.include_router(alerts_router)


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