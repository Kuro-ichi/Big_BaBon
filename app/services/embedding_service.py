"""Embedding với cache, single-flight và model warm-up."""
import asyncio
import hashlib
import threading
from collections import OrderedDict

from app.core.config import settings


class EmbeddingService:
    def __init__(self):
        self._model = None
        self._model_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_size = settings.EMBEDDING_CACHE_SIZE
        # asyncio primitives are bound to an event loop. Keep single-flight
        # tasks separate per loop because this singleton is also used by Celery.
        self._inflight: dict[
            tuple[asyncio.AbstractEventLoop, str],
            asyncio.Task[list[float]],
        ] = {}

    def _ensure_model(self):
        if self._model is None:
            with self._model_lock:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer
                    self._model = SentenceTransformer(settings.EMBEDDING_MODEL)
        return self._model

    def _encode_sync(self, text: str) -> list[float]:
        model = self._ensure_model()
        vec = model.encode(text, normalize_embeddings=True)
        return vec.tolist()

    def _remove_inflight(
        self,
        inflight_key: tuple[asyncio.AbstractEventLoop, str],
        task: asyncio.Task[list[float]],
    ) -> None:
        with self._state_lock:
            if self._inflight.get(inflight_key) is task:
                self._inflight.pop(inflight_key, None)

    async def _compute_and_cache(self, text: str, key: str) -> list[float]:
        vector = await asyncio.to_thread(self._encode_sync, text)
        with self._state_lock:
            self._cache[key] = vector
            self._cache.move_to_end(key)
            if len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return vector

    async def embed(self, text: str) -> list[float]:
        normalized = (text or "").strip()
        if not normalized:
            raise ValueError("Embedding text must not be empty")

        key = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        loop = asyncio.get_running_loop()
        inflight_key = (loop, key)

        # Cache check and in-flight registration must be atomic. Otherwise a
        # completed task can be removed just before another caller registers.
        with self._state_lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached

            task = self._inflight.get(inflight_key)
            if task is None:
                task = loop.create_task(self._compute_and_cache(normalized, key))
                self._inflight[inflight_key] = task
                task.add_done_callback(
                    lambda done, item_key=inflight_key: self._remove_inflight(item_key, done)
                )

        # A disconnected request must not cancel work shared by other waiters.
        return await asyncio.shield(task)

    async def preload(self) -> None:
        """Load model and run one warm-up encode before accepting requests."""
        await asyncio.to_thread(self._encode_sync, "embedding model warmup")


embedding_service = EmbeddingService()
