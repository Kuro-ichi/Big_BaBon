from fastapi import FastAPI
from app.api.chat_routes import router as chat_router
from app.api.health_routes import router as health_router
from app.core.config import settings

app = FastAPI(title=settings.APP_NAME)
app.include_router(health_router, tags=["health"])
app.include_router(chat_router, tags=["chat"])
