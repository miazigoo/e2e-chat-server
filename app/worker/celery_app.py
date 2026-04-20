from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "secure_chat_worker",
    broker=settings.rabbitmq_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    imports=("app.worker.tasks",),
    beat_schedule={
        "cleanup-expired-auth-sessions-every-15-minutes": {
            "task": "app.worker.tasks.cleanup_expired_auth_sessions",
            "schedule": 15 * 60,
        },
        "cleanup-expired-email-codes-every-10-minutes": {
            "task": "app.worker.tasks.cleanup_expired_email_codes",
            "schedule": 10 * 60,
        },
        "cleanup-expired-upload-sessions-every-10-minutes": {
            "task": "app.worker.tasks.cleanup_expired_upload_sessions",
            "schedule": 10 * 60,
        },
        "mark-expired-messages-every-5-minutes": {
            "task": "app.worker.tasks.mark_expired_messages",
            "schedule": 5 * 60,
        },
        "reconcile-presence-last-seen-every-2-minutes": {
            "task": "app.worker.tasks.reconcile_presence_last_seen",
            "schedule": 2 * 60,
        },
    },
)


@celery_app.task(name="app.tasks.ping")
def ping() -> str:
    return "pong"
