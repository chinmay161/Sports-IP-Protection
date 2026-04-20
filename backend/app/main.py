from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.assets import router as assets_router
from app.db.milvus import ensure_collection
from app.db.session import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    await ensure_collection()
    yield


app = FastAPI(title="Sports IP Protection API", lifespan=lifespan)
app.include_router(assets_router)


@app.get("/")
async def read_root() -> dict[str, str]:
    return {"message": "FastAPI is running"}


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}

