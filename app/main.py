from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.api.auth_routes import router as auth_router
from app.api.chat_routes import router as chat_router
from app.api.health_routes import router as health_router
from app.core.config import settings
from app.db.postgres import close_pool
from app.services.cache_service import cache_service
from app.services.embedding_service import embedding_service
from app.services.llm_service import llm_service
from app.services.retrieval_service import retrieval_service


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.EMBEDDING_PRELOAD:
        await embedding_service.preload()
    yield
    await llm_service.close()
    await cache_service.close()
    await retrieval_service.close()
    await close_pool()

app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
app.include_router(health_router, tags=["health"])
app.include_router(auth_router, tags=["auth"])
app.include_router(chat_router, tags=["chat"])

# UI tĩnh — mount cuối cùng để không che /docs, /health, /v1/*
_static_dir = Path(__file__).resolve().parent / "static"
app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
