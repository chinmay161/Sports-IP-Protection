# app/core/config.py
import os
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


BACKEND_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(BACKEND_ENV_PATH)
load_dotenv()


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
    max_download_bytes: int
    geoip_database_path: str | None
    crawler_mode: str
    crawler_discovery_mode: str
    crawler_watchlist_urls: str | None
    visual_crawl_max_pages: int
    visual_crawl_max_images: int
    visual_crawl_max_candidates: int
    visual_phash_threshold: int


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
        max_download_bytes=int(os.getenv("MAX_DOWNLOAD_BYTES", "2147483648")),
        geoip_database_path=os.getenv("GEOIP_DATABASE_PATH"),
        crawler_mode=os.getenv("CRAWLER_MODE", "mock").strip().lower(),
        crawler_discovery_mode=os.getenv("CRAWLER_DISCOVERY_MODE", "hybrid").strip().lower(),
        crawler_watchlist_urls=os.getenv("CRAWLER_WATCHLIST_URLS"),
        visual_crawl_max_pages=int(os.getenv("VISUAL_CRAWL_MAX_PAGES", "50")),
        visual_crawl_max_images=int(os.getenv("VISUAL_CRAWL_MAX_IMAGES", "100")),
        visual_crawl_max_candidates=int(os.getenv("VISUAL_CRAWL_MAX_CANDIDATES", "25")),
        visual_phash_threshold=int(os.getenv("VISUAL_PHASH_THRESHOLD", "18")),
    )
