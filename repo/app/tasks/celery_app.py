from celery import Celery

from app.core.config import settings

celery_app = Celery("medical_ops", broker=settings.redis_url, backend=settings.redis_url)
# Import jobs to register tasks
from . import jobs # noqa: F401
celery_app.conf.beat_schedule = {
    "daily-metrics": {
        "task": "jobs.aggregate_all_daily_metrics",
        "schedule": 60 * 60 * 24,
    },
    "sla-monitor": {
        "task": "jobs.monitor_sla",
        "schedule": 300,
    },
    "task-reminder": {
        "task": "jobs.send_task_reminders",
        "schedule": 600,
    },
    "task-escalation": {
        "task": "jobs.escalate_overdue_tasks",
        "schedule": 300,
    },
    "backup-pruning": {
        "task": "jobs.prune_old_backups",
        "schedule": 60 * 60 * 24,
    },
    "task-timeouts": {
        "task": "jobs.handle_task_timeouts",
        "schedule": 900,
    },
    "export-pruning": {
        "task": "jobs.prune_old_exports",
        "schedule": 60 * 60 * 24,
    },
    "daily-backup": {
        "task": "jobs.backup_database",
        "schedule": 60 * 60 * 24,
    },
}
celery_app.conf.timezone = "UTC"
