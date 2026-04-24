from app.core.celery import celery_app


@celery_app.task
def generate(match_id: str) -> None:
    pass
