"""Celery task discovery entrypoint.

Celery autodiscovery imports ``app.workers.tasks`` for the ``app.workers``
package. Importing these modules registers their decorated tasks on the shared
``app.core.celery.celery_app`` instance.
"""

from app.workers import evidence_task, ingest_task, live_stream_task, scan_task, visual_task, watermark_task  # noqa: F401
