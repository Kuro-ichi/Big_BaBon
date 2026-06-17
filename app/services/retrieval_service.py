import hashlib
import json
import logging
import re
import unicodedata
from typing import Any

from app.core.config import settings
from app.db.postgres import stable_uuid
from app.services.cache_service import cache_service
from app.services.embedding_service import embedding_service


logger = logging.getLogger(__name__)

RETRIEVAL_CACHE_VERSION = 2
TOKEN_RE = re.compile(r"\w+", re.UNICODE)
STOPWORDS = {
    "anh",
    "ban",
    "bao",
    "bi",
    "cai",
    "can",
    "cho",
    "co",
    "cua",
    "duoc",
    "gi",
    "giup",
    "hay",
    "khong",
    "la",
    "minh",
    "nao",
    "nen",
    "nhieu",
    "toi",
    "trong",
    "va",
    "ve",
    "voi",
}


class RetrievalService:
    def __init__(self):
        self._client = None

    def _get_client(self):
        if self._client is None:
            from qdrant_client import AsyncQdrantClient

            self._client = AsyncQdrantClient(
                url=settings.QDRANT_URL,
                api_key=settings.QDRANT_API_KEY or None,
                timeout=settings.QDRANT_TIMEOUT,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    def _to_doc(self, hit):
        payload = hit.payload or {}
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        content = payload.get(settings.QDRANT_PAYLOAD_TEXT) or payload.get("page_content") or payload.get("text") or ""
        source = (
            payload.get(settings.QDRANT_PAYLOAD_SOURCE)
            or payload.get("source")
            or metadata.get(settings.QDRANT_PAYLOAD_SOURCE)
            or metadata.get("source")
        )
        return {
            "id": str(hit.id),
            "content": content,
            "source": source,
            "score": getattr(hit, "score", 0.0) or 0.0,
            "payload": payload,
            "metadata": metadata,
        }

    def _cache_key(self, namespace: str, payload: dict) -> str:
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return f"{namespace}:{digest}"

    def _fold(self, text: str) -> str:
        normalized = unicodedata.normalize("NFD", (text or "").lower())
        folded = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
        return folded.replace("đ", "d")

    def _tokens(self, text: str) -> set[str]:
        return {
            token
            for token in TOKEN_RE.findall(self._fold(text))
            if len(token) > 1 and token not in STOPWORDS
        }

    def _keyword_score(self, query: str, content: str) -> float:
        query_terms = self._tokens(query)
        content_terms = self._tokens(content)
        if not query_terms or not content_terms:
            return 0.0
        return len(query_terms.intersection(content_terms)) / len(query_terms)

    def _as_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, (tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []

    def _metadata_values(self, metadata: dict, key: str) -> set[str]:
        value = metadata.get(key)
        if isinstance(value, list):
            return {self._fold(str(item).strip()) for item in value if str(item).strip()}
        value = self._fold(str(value or ""))
        return {item.strip() for item in re.split(r"[,;/|]", value) if item.strip()}

    def _doc_matches_filters(self, doc: dict, filters: dict | None) -> bool:
        if not filters:
            return True

        metadata = doc.get("metadata", {}) or {}
        source_types = self._as_list(filters.get("preferred_source_types") or filters.get("source_type"))
        languages = self._as_list(filters.get("language"))
        risk_levels = self._as_list(filters.get("risk_level"))

        if source_types:
            source_type = str(metadata.get("source_type") or doc.get("source_type") or "").lower()
            if source_type not in {item.lower() for item in source_types}:
                return False
        if languages and metadata.get("language"):
            if str(metadata.get("language")).lower() not in {item.lower() for item in languages}:
                return False
        if risk_levels and metadata.get("risk_level"):
            if str(metadata.get("risk_level")).lower() not in {item.lower() for item in risk_levels}:
                return False
        return True

    def _build_qdrant_filter(self, filters: dict | None):
        if not filters:
            return None

        from qdrant_client.http import models as rest

        must = []
        source_types = self._as_list(filters.get("preferred_source_types") or filters.get("source_type"))
        languages = self._as_list(filters.get("language"))
        risk_levels = self._as_list(filters.get("risk_level"))

        if source_types:
            must.append(rest.FieldCondition(
                key="metadata.source_type",
                match=rest.MatchAny(any=source_types),
            ))
        if languages:
            must.append(rest.FieldCondition(
                key="metadata.language",
                match=rest.MatchAny(any=languages),
            ))
        if risk_levels:
            must.append(rest.FieldCondition(
                key="metadata.risk_level",
                match=rest.MatchAny(any=risk_levels),
            ))
        return rest.Filter(must=must) if must else None

    def _safety_boost(
        self,
        doc: dict,
        preferred_conditions: list[str] | None = None,
        preferred_source_types: list[str] | None = None,
    ) -> float:
        metadata = doc.get("metadata", {}) or {}
        source_type = str(metadata.get("source_type") or doc.get("source_type") or "").lower()
        risk_level = str(metadata.get("risk_level") or "").lower()
        boost = 0.0

        safety_requested = bool(
            preferred_source_types
            and "safety_guardrail" in {item.lower() for item in preferred_source_types}
        )
        if source_type == "safety_guardrail" and safety_requested:
            boost += 0.6
        if risk_level == "high":
            boost += 0.2
        if preferred_source_types and source_type in {item.lower() for item in preferred_source_types}:
            boost += 0.3
        if preferred_conditions:
            doc_conditions = self._metadata_values(metadata, "condition")
            wanted = {item.lower() for item in preferred_conditions}
            if doc_conditions.intersection(wanted):
                boost += 0.4
        return boost

    def _lexical_overlap_score(self, query: str, text: str) -> float:
        query_terms = self._tokens(query)
        text_terms = self._tokens(text)
        if not query_terms or not text_terms:
            return 0.0
        return len(query_terms.intersection(text_terms)) / len(query_terms)

    def _phrase_boost(self, query: str, text: str) -> float:
        query_tokens = [
            token
            for token in TOKEN_RE.findall(self._fold(query))
            if len(token) > 1 and token not in STOPWORDS
        ]
        haystack = f" {self._fold(text)} "
        boost = 0.0
        for size in (4, 3, 2):
            for start in range(0, max(len(query_tokens) - size + 1, 0)):
                phrase = " ".join(query_tokens[start:start + size])
                if phrase and f" {phrase} " in haystack:
                    boost += 0.10 * (size - 1)
        return min(boost, 0.6)

    def _metadata_source_boost(self, metadata: dict) -> float:
        source_type = str(metadata.get("source_type") or "").lower()
        if source_type == "food_composition_table":
            return 0.08
        if source_type == "safety_guardrail":
            return 0.03
        if source_type in {"clinical_nutrition_guideline", "clinical_patient_guidance"}:
            return 0.16
        if source_type in {"nutrition_textbook", "public_health_guideline"}:
            return 0.08
        return 0.0

    def _condition_boost(self, metadata: dict, preferred_conditions: list[str] | None) -> float:
        if not preferred_conditions:
            return 0.0
        doc_conditions = self._metadata_values(metadata, "condition")
        wanted = {self._fold(item) for item in preferred_conditions if item}
        if doc_conditions.intersection(wanted):
            return 0.45
        if "general" in doc_conditions and wanted:
            return 0.08
        return 0.0

    def _preferred_source_boost(self, metadata: dict, preferred_source_types: list[str] | None) -> float:
        if not preferred_source_types:
            return 0.0
        source_type = self._fold(str(metadata.get("source_type") or ""))
        preferred = {self._fold(item) for item in preferred_source_types if item}
        return 0.30 if source_type and source_type in preferred else 0.0

    def _food_name_boost(self, query: str, metadata: dict) -> float:
        food_name = str(metadata.get("food_name") or "")
        if not food_name:
            return 0.0
        query_folded = self._fold(query)
        food_folded = self._fold(food_name)
        if food_folded and food_folded in query_folded:
            return 1.0
        query_terms = self._tokens(query)
        food_terms = self._tokens(food_name)
        if not food_terms:
            return 0.0
        overlap = len(query_terms.intersection(food_terms)) / len(food_terms)
        if overlap >= 0.75:
            return 0.75
        if overlap >= 0.5:
            return 0.45
        if overlap > 0:
            return 0.18
        return 0.0

    def _food_query_terms(self, query: str) -> set[str]:
        terms = self._tokens(query)
        nutrition_terms = {"calo", "kcal", "protein", "lipid", "glucid", "natri", "sat", "kem"}
        return {term for term in terms if term not in nutrition_terms}

    def _food_query_fit_boost(self, query: str, metadata: dict, searchable_text: str) -> float:
        if str(metadata.get("source_type") or "") != "food_composition_table":
            return 0.0
        food_terms = self._food_query_terms(query)
        if not food_terms:
            return 0.0
        haystack_terms = self._tokens(" ".join([
            str(metadata.get("food_name") or ""),
            str(metadata.get("title") or ""),
            searchable_text,
        ]))
        overlap_count = len(food_terms.intersection(haystack_terms))
        if overlap_count == len(food_terms):
            return 1.2
        if overlap_count == 0:
            return -0.8
        return -0.25

    def _rerank_score(
        self,
        query: str,
        doc: dict,
        preferred_conditions: list[str] | None,
        preferred_source_types: list[str] | None,
    ) -> float:
        metadata = doc.get("metadata", {}) or {}
        title = str(metadata.get("title") or doc.get("title") or "")
        food_name = str(metadata.get("food_name") or "")
        searchable_text = " ".join([
            title,
            food_name,
            str(metadata.get("condition") or ""),
            str(metadata.get("source_id") or ""),
            doc.get("content", "") or "",
        ])
        vector_score = max(min(float(doc.get("score") or 0.0), 1.0), 0.0)
        score = (
            vector_score * 0.12
            + self._lexical_overlap_score(query, searchable_text)
            + 0.6 * self._lexical_overlap_score(query, title)
            + 0.9 * self._lexical_overlap_score(query, food_name)
            + self._phrase_boost(query, searchable_text)
            + self._food_name_boost(query, metadata)
            + self._food_query_fit_boost(query, metadata, searchable_text)
            + self._metadata_source_boost(metadata)
            + self._condition_boost(metadata, preferred_conditions)
            + self._preferred_source_boost(metadata, preferred_source_types)
            + self._safety_boost(doc, preferred_conditions, preferred_source_types)
        )
        return round(score, 6)

    async def search_kb_vector(self, query: str, filters: dict, top_k: int = 8):
        cache_key = self._cache_key(
            "retrieval:kb_vector",
            {
                "collection": settings.QDRANT_COLLECTION,
                "query": query,
                "filters": filters,
                "top_k": top_k,
                "version": RETRIEVAL_CACHE_VERSION,
            },
        )
        cached = await cache_service.get_json(cache_key)
        if cached is not None:
            return cached

        vector = await embedding_service.embed(query)
        query_vector = (settings.QDRANT_VECTOR_NAME, vector) if settings.QDRANT_VECTOR_NAME else vector
        client = self._get_client()
        query_filter = self._build_qdrant_filter(filters)
        try:
            hits = await client.search(
                collection_name=settings.QDRANT_COLLECTION,
                query_vector=query_vector,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
            )
        except Exception as exc:
            logger.warning(
                "qdrant filtered vector search failed (collection=%s), retrying without filter: %s",
                settings.QDRANT_COLLECTION,
                exc,
            )
            hits = await client.search(
                collection_name=settings.QDRANT_COLLECTION,
                query_vector=query_vector,
                limit=top_k,
                with_payload=True,
            )
        docs = [self._to_doc(h) for h in hits]
        await cache_service.set_json(cache_key, docs)
        return docs

    async def search_kb_keyword(self, query: str, filters: dict, top_k: int = 5):
        cache_key = self._cache_key(
            "retrieval:kb_keyword",
            {
                "collection": settings.QDRANT_COLLECTION,
                "query": query,
                "filters": filters,
                "top_k": top_k,
                "version": RETRIEVAL_CACHE_VERSION,
            },
        )
        cached = await cache_service.get_json(cache_key)
        if cached is not None:
            return cached

        client = self._get_client()
        docs = []
        offset = None
        scanned = 0
        try:
            while True:
                points, offset = await client.scroll(
                    collection_name=settings.QDRANT_COLLECTION,
                    scroll_filter=None,
                    limit=256,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                scanned += len(points)
                for point in points:
                    doc = self._to_doc(point)
                    if not self._doc_matches_filters(doc, filters):
                        continue
                    score = self._keyword_score(query, doc.get("content", ""))
                    if score > 0:
                        doc["score"] = score
                        doc["source_type"] = "kb_keyword"
                        docs.append(doc)
                if offset is None or scanned >= settings.KEYWORD_SCROLL_MAX_POINTS:
                    break
        except Exception:
            return []

        docs.sort(key=lambda item: item.get("score", 0), reverse=True)
        docs = docs[:top_k]
        await cache_service.set_json(cache_key, docs)
        return docs

    async def search_user_memory(self, query: str, user_id: str, top_k: int = 3):
        from qdrant_client.http import models as rest

        if not user_id:
            return []

        vector = await embedding_service.embed(query)
        query_vector = (settings.QDRANT_VECTOR_NAME, vector) if settings.QDRANT_VECTOR_NAME else vector
        query_filter = rest.Filter(
            must=[
                rest.FieldCondition(
                    key="user_id",
                    match=rest.MatchValue(value=str(user_id)),
                )
            ]
        )
        client = self._get_client()
        try:
            hits = await client.search(
                collection_name=settings.QDRANT_MEMORY_COLLECTION,
                query_vector=query_vector,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
            )
        except Exception:
            return []

        docs = [self._to_doc(h) for h in hits]
        for doc in docs:
            doc["source_type"] = "memory"
        return docs

    async def upsert_user_memory(self, user_id: str, session_id: str, content: str, metadata: dict | None = None):
        from qdrant_client.http import models as rest

        if not content.strip():
            return None

        vector = await embedding_service.embed(content)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        point_id = str(stable_uuid(f"{user_id}:{session_id}:{digest}"))
        payload = {
            "text": content,
            "source": "user_memory",
            "source_type": "memory",
            "user_id": str(user_id),
            "user_uuid": str(stable_uuid(user_id)),
            "session_id": str(session_id),
            "metadata": metadata or {},
        }
        client = self._get_client()
        try:
            await client.get_collection(settings.QDRANT_MEMORY_COLLECTION)
        except Exception:
            await client.create_collection(
                collection_name=settings.QDRANT_MEMORY_COLLECTION,
                vectors_config=rest.VectorParams(size=len(vector), distance=rest.Distance.COSINE),
            )
        await client.upsert(
            collection_name=settings.QDRANT_MEMORY_COLLECTION,
            points=[rest.PointStruct(id=point_id, vector=vector, payload=payload)],
        )
        return point_id

    def dedupe_documents(self, documents):
        seen = set()
        output = []
        for doc in documents:
            key = doc.get("id") or doc.get("content")
            if key not in seen:
                seen.add(key)
                output.append(doc)
        return output

    async def rerank(self, query: str, documents: list):
        return sorted(documents, key=lambda x: x.get("score", 0), reverse=True)

    async def rerank_with_plan(self, query: str, documents: list, search_plan: dict):
        preferred_conditions = search_plan.get("condition") if isinstance(search_plan.get("condition"), list) else None
        preferred_source_types = search_plan.get("preferred_source_types")
        ranked = []
        for doc in documents:
            new_doc = dict(doc)
            base_score = float(new_doc.get("score") or 0.0)
            rerank_score = self._rerank_score(
                query,
                new_doc,
                preferred_conditions,
                preferred_source_types,
            )
            new_doc["original_score"] = base_score
            new_doc["rerank_score"] = rerank_score
            new_doc["score"] = rerank_score
            ranked.append(new_doc)
        return sorted(ranked, key=lambda x: x.get("score", 0), reverse=True)

    def extract_subject(self, query: str, documents: list) -> str | None:
        query_terms = self._tokens(query)
        best_subject = None
        best_score = 0.0
        for doc in documents:
            metadata = doc.get("metadata", {}) or {}
            if metadata.get("source_type") != "food_composition_table":
                continue
            subject = str(metadata.get("food_name") or "").strip()
            if not subject:
                title = str(metadata.get("title") or "").strip()
                subject = title.rsplit(" - ", 1)[-1].strip() if title else ""
            if not subject:
                continue
            subject_terms = self._tokens(subject)
            if not subject_terms:
                continue
            overlap = len(query_terms.intersection(subject_terms)) / len(subject_terms)
            contains = self._fold(subject) in self._fold(query) or self._fold(query) in self._fold(subject)
            score = overlap + (1.0 if contains else 0.0)
            if score > best_score:
                best_score = score
                best_subject = subject
        return best_subject if best_score >= 0.5 else None

    def trim_by_token_budget(
        self,
        documents: list,
        max_tokens: int = 2200,
        max_documents: int = 8,
        min_score: float = -0.2,
    ):
        eligible = [doc for doc in documents if float(doc.get("score") or 0.0) >= min_score]
        if not eligible and documents:
            eligible = documents[:1]
        selected = []
        used = 0
        for doc in eligible:
            if len(selected) >= max_documents:
                break
            # xấp xỉ token: 1 token ~ 4 ký tự (tiếng Việt thô).
            # Thay bằng tokenizer thật nếu cần chính xác hơn.
            cost = max(len(doc.get("content", "")) // 4, 1)
            if selected and used + cost > max_tokens:
                break
            selected.append(doc)
            used += cost
        return selected


retrieval_service = RetrievalService()
