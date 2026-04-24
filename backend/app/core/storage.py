from pathlib import Path

import boto3

from app.core.config import get_settings


def _client():
    settings = get_settings()
    kwargs: dict[str, str] = {}
    if settings.aws_region:
        kwargs["region_name"] = settings.aws_region
    if settings.s3_endpoint_url:
        kwargs["endpoint_url"] = settings.s3_endpoint_url
    return boto3.client("s3", **kwargs)


def _bucket_name() -> str:
    bucket = get_settings().s3_bucket_name
    if not bucket:
        raise RuntimeError("S3_BUCKET_NAME is required")
    return bucket


def upload_file(local_path: str | Path, s3_key: str) -> None:
    _client().upload_file(str(local_path), _bucket_name(), s3_key)


def download_file(s3_key: str, local_path: str | Path) -> None:
    Path(local_path).parent.mkdir(parents=True, exist_ok=True)
    _client().download_file(_bucket_name(), s3_key, str(local_path))


def generate_presigned_url(s3_key: str, expires_in: int = 3600) -> str:
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": _bucket_name(), "Key": s3_key},
        ExpiresIn=expires_in,
    )
