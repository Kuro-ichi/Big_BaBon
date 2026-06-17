import json

import redis.asyncio as redis

from app.core.config import settings


class CacheService:
    def __init__(self):
        self._client = None

    def _get_client(self):
        if self._client is None:
            self._client = redis.Redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=settings.REDIS_CONNECT_TIMEOUT,
                socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
            )
        return self._client

    async def get_json(self, key: str):
        try:
            raw = await self._get_client().get(key)
        except redis.RedisError:
            return None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    async def set_json(self, key: str, value, ttl_seconds: int | None = None) -> None:
        ttl = ttl_seconds or settings.REDIS_CACHE_TTL_SECONDS
        try:
            await self._get_client().set(key, json.dumps(value, ensure_ascii=False), ex=ttl)
        except redis.RedisError:
            return None

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


cache_service = CacheService()
