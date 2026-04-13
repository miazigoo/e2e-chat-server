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
)


@celery_app.task(name="app.tasks.ping")
def ping() -> str:
    return "pong"
