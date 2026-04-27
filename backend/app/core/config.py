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
    aws_access_key_id: str | None
    aws_secret_access_key: str | None
    aws_region: str | None
    s3_endpoint_url: str | None
    live_bucket: str | None
    cloudfront_distribution_id: str | None
    cloudfront_key_pair_id: str | None
    cloudfront_private_key_path: str | None
    live_stream_enabled: bool
    inbound_poll_interval_s: int
    inbound_max_segments: int
    allow_real_cdn_requests: bool
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
    gemini_api_key: str | None
    gemini_model: str
    gemini_enabled: bool
    google_application_credentials: str | None
    video_intelligence_enabled: bool


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
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        aws_region=os.getenv("AWS_REGION"),
        s3_endpoint_url=os.getenv("S3_ENDPOINT_URL"),
        live_bucket=os.getenv("LIVE_BUCKET", "sports-ip-live"),
        cloudfront_distribution_id=os.getenv("CLOUDFRONT_DISTRIBUTION_ID"),
        cloudfront_key_pair_id=os.getenv("CLOUDFRONT_KEY_PAIR_ID"),
        cloudfront_private_key_path=os.getenv("CLOUDFRONT_PRIVATE_KEY_PATH"),
        live_stream_enabled=_bool_env("LIVE_STREAM_ENABLED", "true"),
        inbound_poll_interval_s=int(os.getenv("INBOUND_POLL_INTERVAL_S", "15")),
        inbound_max_segments=int(os.getenv("INBOUND_MAX_SEGMENTS", "5")),
        allow_real_cdn_requests=_bool_env("ALLOW_REAL_CDN_REQUESTS"),
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
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        gemini_enabled=_bool_env("GEMINI_ENABLED", "true"),
        google_application_credentials=os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
        video_intelligence_enabled=_bool_env("VIDEO_INTELLIGENCE_ENABLED", "true"),
    )
