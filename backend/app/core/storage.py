from pathlib import Path
from shutil import copyfile
from urllib.parse import quote

import boto3

from app.core.config import get_settings


LOCAL_ARTIFACT_ROOT = Path("media_store") / "generated"


def _using_s3() -> bool:
    return bool(get_settings().s3_bucket_name)


def _local_path(s3_key: str) -> Path:
    candidate = LOCAL_ARTIFACT_ROOT / s3_key
    root = LOCAL_ARTIFACT_ROOT.resolve()
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise RuntimeError(f"Invalid storage key: {s3_key}")
    return candidate


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
    if _using_s3():
        _client().upload_file(str(local_path), _bucket_name(), s3_key)
        return

    destination = _local_path(s3_key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    copyfile(local_path, destination)


def download_file(s3_key: str, local_path: str | Path) -> None:
    Path(local_path).parent.mkdir(parents=True, exist_ok=True)
    if _using_s3():
        _client().download_file(_bucket_name(), s3_key, str(local_path))
        return

    copyfile(_local_path(s3_key), local_path)


def generate_presigned_url(s3_key: str, expires_in: int = 3600) -> str:
    if not _using_s3():
        return f"/files/{quote(s3_key, safe='/')}"

    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": _bucket_name(), "Key": s3_key},
        ExpiresIn=expires_in,
    )
