from typing import Any

import boto3
from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.celery import celery_app
from app.core.config import get_settings
from app.core.redis import redis_client
from app.db.milvus import _connect, utility
from app.db.session import SessionLocal


router = APIRouter()


async def _check_postgres() -> None:
    async with SessionLocal() as session:
        await session.execute(text("SELECT 1"))


async def _check_redis() -> None:
    await redis_client.ping()


def _check_milvus() -> None:
    if utility is None:
        raise RuntimeError("pymilvus is required")
    _connect()
    utility.get_server_version()


def _s3_client():
    settings = get_settings()
    kwargs: dict[str, str] = {}
    if settings.aws_region:
        kwargs["region_name"] = settings.aws_region
    if settings.s3_endpoint_url:
        kwargs["endpoint_url"] = settings.s3_endpoint_url
    if settings.aws_access_key_id:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
    if settings.aws_secret_access_key:
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return boto3.client("s3", **kwargs)


def _check_minio() -> None:
    _s3_client().list_buckets()


def _celery_worker_count() -> int:
    responses: dict[str, Any] | None = celery_app.control.inspect().ping()
    return len(responses or {})


@router.get("/health", response_model=None)
async def health() -> JSONResponse | dict[str, Any]:
    checks: dict[str, str] = {}
    failures: dict[str, str] = {}

    for name, check in (
        ("postgres", _check_postgres),
        ("redis", _check_redis),
    ):
        try:
            await check()
            checks[name] = "ok"
        except Exception as exc:
            checks[name] = "failed"
            failures[name] = str(exc)

    for name, check in (
        ("milvus", _check_milvus),
        ("minio", _check_minio),
    ):
        try:
            await run_in_threadpool(check)
            checks[name] = "ok"
        except Exception as exc:
            checks[name] = "failed"
            failures[name] = str(exc)

    try:
        celery_workers = await run_in_threadpool(_celery_worker_count)
        if celery_workers < 1:
            raise RuntimeError("no Celery workers responded")
    except Exception as exc:
        celery_workers = 0
        failures["celery_workers"] = str(exc)

    payload: dict[str, str | int | dict[str, str]] = {
        "status": "ok" if not failures else "failed",
        **checks,
        "celery_workers": celery_workers,
    }

    if failures:
        payload["failures"] = failures
        return JSONResponse(status_code=503, content=payload)

    return payload
