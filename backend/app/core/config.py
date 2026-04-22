# app/core/config.py
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(slots=True)
class Settings:
    database_url: str
    celery_broker_url: str
    celery_result_backend: str
    milvus_uri: str
    milvus_token: str | None
    milvus_collection_name: str
    milvus_required: bool
    temp_root: Path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    milvus_required = os.getenv("MILVUS_REQUIRED", "false").strip().lower() in {"1", "true", "yes", "on"}
    return Settings(
        database_url=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./sports_ip.db"),
        celery_broker_url=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
        celery_result_backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
        milvus_uri=os.getenv("MILVUS_URI", "http://localhost:19530"),
        milvus_token=os.getenv("MILVUS_TOKEN"),
        milvus_collection_name=os.getenv("MILVUS_COLLECTION_NAME", "video_fingerprints"),
        milvus_required=milvus_required,
        temp_root=Path(os.getenv("TEMP_ROOT", "/tmp/sports_ip_temp")),
    )