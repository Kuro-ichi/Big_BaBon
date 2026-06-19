import hashlib

import httpx

from app.core.config import settings
from app.services.cache_service import cache_service


class WebSearchService:
    async def search_web(self, query: str, max_results: int | None = None):
        if not settings.WEB_FALLBACK_ENABLED:
            return []
        if settings.WEB_FALLBACK_PROVIDER.lower() != "tavily":
            return []
        return await self._search_tavily(query, max_results=max_results)

    async def _search_tavily(self, query: str, max_results: int | None = None):
        if not settings.TAVILY_API_KEY:
            return []

        limit = max_results or settings.TAVILY_MAX_RESULTS
        cache_key = "web:tavily:" + hashlib.sha256(
            f"{query}:{limit}:{settings.TAVILY_SEARCH_DEPTH}:{settings.TAVILY_INCLUDE_RAW_CONTENT}".encode("utf-8")
        ).hexdigest()
        cached = await cache_service.get_json(cache_key)
        if cached is not None:
            return cached

        payload = {
            "query": query,
            "search_depth": settings.TAVILY_SEARCH_DEPTH,
            "max_results": limit,
            "include_answer": False,
            "include_raw_content": "markdown" if settings.TAVILY_INCLUDE_RAW_CONTENT else False,
            "include_images": False,
            "include_favicon": True,
            "include_usage": True,
        }
        headers = {"Authorization": f"Bearer {settings.TAVILY_API_KEY}"}

        try:
            async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT) as client:
                response = await client.post("https://api.tavily.com/search", json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError):
            return []

        docs = []
        for index, item in enumerate(data.get("results", [])):
            content = item.get("raw_content") or item.get("content") or ""
            if not content:
                continue
            url = item.get("url") or ""
            title = item.get("title") or url or f"web-{index}"
            docs.append(
                {
                    "id": "web-" + hashlib.sha256(f"{url}:{title}:{index}".encode("utf-8")).hexdigest()[:16],
                    "source_type": "web",
                    "title": title,
                    "url": url,
                    "source": url,
                    "content": content,
                    "score": float(item.get("score") or 0.0),
                    "payload": item,
                    "metadata": {
                        "provider": "tavily",
                        "favicon": item.get("favicon"),
                        "response_time": data.get("response_time"),
                        "usage": data.get("usage"),
                    },
                }
            )

        await cache_service.set_json(cache_key, docs)
        return docs


web_search_service = WebSearchService()
