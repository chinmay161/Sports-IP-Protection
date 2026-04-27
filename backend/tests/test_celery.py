from app.core.celery import celery_app


def test_worker_tasks_are_registered() -> None:
    assert "app.workers.ingest_task.ingest_asset" in celery_app.tasks
    assert "app.workers.ingest_task.finalize_asset" in celery_app.tasks
    assert "app.workers.scan_task.scan_asset" in celery_app.tasks
    assert "app.workers.scan_task.scan_all_assets" in celery_app.tasks
    assert "app.workers.visual_task.discover_visual_candidates" in celery_app.tasks


def test_beat_schedule_uses_registered_scan_task() -> None:
    task_name = celery_app.conf.beat_schedule["scan-all-assets"]["task"]
    assert task_name == "app.workers.scan_task.scan_all_assets"
    assert task_name in celery_app.tasks
