from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "chatbot_workers",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.workers.summary_worker",
        "app.workers.memory_worker",
        "app.workers.embedding_worker",
        "app.workers.ingest_worker",
    ],
)

# Import task modules so they are registered in local scripts and worker boot.
from app.workers import embedding_worker, ingest_worker, memory_worker, summary_worker  # noqa: E402,F401
