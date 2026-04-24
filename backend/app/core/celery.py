import sys
from importlib import import_module

from app.core.config import get_settings

try:
    from celery import Celery
    from celery.schedules import crontab
except ImportError:  # pragma: no cover - exercised only when dependency is absent
    class _CeleryConf(dict):
        def __getattr__(self, name):
            try:
                return self[name]
            except KeyError as exc:
                raise AttributeError(name) from exc

        def __setattr__(self, name, value) -> None:
            self[name] = value

    class Celery:  # type: ignore[override]
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs
            self.conf = _CeleryConf()
            self.tasks = {}

        def task(self, *args, **kwargs):
            def decorator(func):
                task_name = kwargs.get("name") or f"{func.__module__}.{func.__name__}"
                self.tasks[task_name] = func
                func.delay = lambda *delay_args, **delay_kwargs: type(
                    "AsyncResultStub",
                    (),
                    {"id": f"local-{delay_kwargs.get('asset_id', 'task')}"},
                )()
                return func

            if args and callable(args[0]) and not kwargs:
                return decorator(args[0])
            return decorator

        def autodiscover_tasks(self, packages, related_name="tasks", force=False):
            for package in packages:
                module_name = package if related_name is None else f"{package}.{related_name}"
                import_module(module_name)

    def crontab(*args, **kwargs):  # type: ignore[no-untyped-def]
        return {"crontab_args": args, "crontab_kwargs": kwargs}


settings = get_settings()
celery_app = Celery(
    "sports_ip_protection",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.autodiscover_tasks(["app.workers"], force=True)

if sys.platform.startswith("win"):
    celery_app.conf.update(worker_pool="solo", worker_concurrency=1)

celery_app.conf.beat_schedule = {
    "scan-all-assets": {
        "task": "app.workers.scan_task.scan_all_assets",
        "schedule": crontab(minute=0, hour="*/6"),
    },
}
