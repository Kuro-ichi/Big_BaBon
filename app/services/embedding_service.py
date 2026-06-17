"""Embed query bằng sentence-transformers (vietnamese-sbert).

Model load lazy (1 lần), encode chạy trong thread để không block event loop.
"""
import asyncio
import hashlib
import threading
from collections import OrderedDict

from app.core.config import settings


class EmbeddingService:
    def __init__(self):
        self._model = None
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, list] = OrderedDict()
        self._cache_size = 512

    def _ensure_model(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer
                    self._model = SentenceTransformer(settings.EMBEDDING_MODEL)
        return self._model

    def _encode_sync(self, text: str) -> list:
        model = self._ensure_model()
        vec = model.encode(text, normalize_embeddings=True)
        return vec.tolist()

    async def embed(self, text: str) -> list:
        key = hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        vector = await asyncio.to_thread(self._encode_sync, text)
        self._cache[key] = vector
        self._cache.move_to_end(key)
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return vector


embedding_service = EmbeddingService()
