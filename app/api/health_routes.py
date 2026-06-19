import asyncio
import time

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.db.postgres import get_pool
from app.services.cache_service import cache_service
from app.services.retrieval_service import retrieval_service


router = APIRouter()


async def _timed_check(check):
    started = time.perf_counter()
    try:
        await asyncio.wait_for(check(), timeout=5.0)
        status = "up"
    except Exception:
        status = "down"
    return {
        "status": status,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    }


async def _check_postgres():
    pool = await get_pool()
    if await pool.fetchval("SELECT 1") != 1:
        raise RuntimeError("PostgreSQL check failed")


async def _check_redis():
    if not await cache_service._get_client().ping():
        raise RuntimeError("Redis check failed")


async def _check_qdrant():
    await retrieval_service._get_client().get_collection(settings.QDRANT_COLLECTION)


async def _check_ollama():
    if settings.LLM_PROVIDER.lower() not in {"local", "ollama"}:
        return
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(f"{settings.OLLAMA_URL.rstrip('/')}/api/tags")
        response.raise_for_status()
        models = {str(item.get("name") or "") for item in response.json().get("models", [])}
        required = {
            settings.LLM_MODEL_LIGHT,
            settings.LLM_MODEL_HEAVY,
            settings.LLM_MODEL_ROUTER or settings.LLM_MODEL_LIGHT,
        }
        if not all(any(name == model or name.startswith(f"{model}:") for name in models) for model in required):
            raise RuntimeError("Required Ollama model is missing")


@router.get("/health/live")
async def liveness_check():
    return {"status": "ok"}


@router.get("/health")
@router.get("/health/ready")
async def readiness_check():
    names = ("postgres", "redis", "qdrant", "ollama")
    results = await asyncio.gather(
        _timed_check(_check_postgres),
        _timed_check(_check_redis),
        _timed_check(_check_qdrant),
        _timed_check(_check_ollama),
    )
    checks = dict(zip(names, results))

    auth_ready = bool(
        settings.AUTH_REQUIRED
        and settings.JWT_SECRET != "change-me"
        and len(settings.JWT_SECRET) >= 32
    )
    checks["authentication"] = {"status": "up" if auth_ready else "down"}
    ready = all(item["status"] == "up" for item in checks.values())
    payload = {"status": "ready" if ready else "not_ready", "checks": checks}
    return JSONResponse(status_code=200 if ready else 503, content=payload)
