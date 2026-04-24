# app/core/config.py
import os
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _bool_env(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


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
    watermark_secret_key: str | None
    s3_bucket_name: str | None
    aws_region: str | None
    s3_endpoint_url: str | None
    redis_url: str
    auth_disabled: bool
    geoip_database_path: str | None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        database_url=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./sports_ip.db"),
        celery_broker_url=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
        celery_result_backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
        milvus_uri=os.getenv("MILVUS_URI", "http://localhost:19530"),
        milvus_token=os.getenv("MILVUS_TOKEN"),
        milvus_collection_name=os.getenv("MILVUS_COLLECTION_NAME", "video_fingerprints"),
        milvus_required=_bool_env("MILVUS_REQUIRED"),
        temp_root=Path(os.getenv("TEMP_ROOT", str(Path(tempfile.gettempdir()) / "sports_ip_temp"))),
        watermark_secret_key=os.getenv("WATERMARK_SECRET_KEY"),
        s3_bucket_name=os.getenv("S3_BUCKET_NAME"),
        aws_region=os.getenv("AWS_REGION"),
        s3_endpoint_url=os.getenv("S3_ENDPOINT_URL"),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/2"),
        auth_disabled=_bool_env("AUTH_DISABLED"),
        geoip_database_path=os.getenv("GEOIP_DATABASE_PATH"),
    )
