import sys

from app.core.config import get_settings

try:
    from celery import Celery
    from celery.schedules import crontab
except ImportError:  # pragma: no cover - exercised only when dependency is absent
    class Celery:  # type: ignore[override]
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs
            self.conf = {}

        def task(self, *args, **kwargs):
            def decorator(func):
                func.delay = lambda *delay_args, **delay_kwargs: type(
                    "AsyncResultStub",
                    (),
                    {"id": f"local-{delay_kwargs.get('asset_id', 'task')}"},
                )()
                return func

            if args and callable(args[0]) and not kwargs:
                return decorator(args[0])
            return decorator

    def crontab(*args, **kwargs):  # type: ignore[no-untyped-def]
        return {"crontab_args": args, "crontab_kwargs": kwargs}


settings = get_settings()
celery_app = Celery(
    "sports_ip_protection",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

if sys.platform.startswith("win"):
    celery_app.conf.update(worker_pool="solo", worker_concurrency=1)

celery_app.conf.beat_schedule = {
    "scan-all-assets": {
        "task": "workers.scan_task.scan_all_assets",
        "schedule": crontab(minute=0, hour="*/6"),
    },
}
