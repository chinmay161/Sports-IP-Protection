import asyncio
import logging

from app.core.celery import celery_app
from app.db.session import SessionLocal
from app.services.evidence import EvidenceError, EvidenceTransientError, generate as generate_evidence


logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def generate(self, match_id: str) -> dict[str, str]:
    try:
        return asyncio.run(_generate_impl(match_id))
    except EvidenceTransientError as exc:
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries)) from exc
    except EvidenceError:
        logger.exception("evidence_generation_permanent_failure match_id=%s", match_id)
        raise


async def _generate_impl(match_id: str) -> dict[str, str]:
    async with SessionLocal() as db:
        package = await generate_evidence(match_id, db)
        return {
            "match_id": package.match_id,
            "pdf_s3_key": package.pdf_s3_key,
            "package_hash": package.package_hash,
        }
