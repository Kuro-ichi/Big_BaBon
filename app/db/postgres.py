from __future__ import annotations

import uuid
import asyncio

import asyncpg

from app.core.config import settings

_pool: asyncpg.Pool | None = None
_pool_loop: asyncio.AbstractEventLoop | None = None


def stable_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return uuid.uuid5(uuid.NAMESPACE_URL, str(value))


async def get_pool() -> asyncpg.Pool:
    global _pool, _pool_loop
    current_loop = asyncio.get_running_loop()
    if _pool is not None and (_pool_loop is not current_loop or _pool_loop.is_closed()):
        _pool.terminate()
        _pool = None
        _pool_loop = None

    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=settings.DATABASE_URL,
            min_size=1,
            max_size=5,
            timeout=settings.DATABASE_CONNECT_TIMEOUT,
        )
        _pool_loop = current_loop
    return _pool


async def close_pool() -> None:
    global _pool, _pool_loop
    if _pool is not None:
        current_loop = asyncio.get_running_loop()
        if _pool_loop is current_loop and not current_loop.is_closed():
            await _pool.close()
        else:
            _pool.terminate()
        _pool = None
        _pool_loop = None
