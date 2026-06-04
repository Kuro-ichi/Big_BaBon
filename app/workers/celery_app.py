from celery import Celery
from app.core.config import settings

celery_app = Celery("chatbot_workers", broker=settings.REDIS_URL, backend=settings.REDIS_URL)
