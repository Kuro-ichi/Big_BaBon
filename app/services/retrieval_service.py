import re
from typing import Any


class RetrievalService:
    async def search_kb_vector(self, query: str, filters: dict, top_k: int = 8):
        return []

    async def search_kb_keyword(self, query: str, filters: dict, top_k: int = 5):
        return []

    async def search_user_memory(self, query: str, user_id: str, top_k: int = 3):
        # Bắt buộc filter user_id khi triển khai thật.
        return []

    def merge_documents(self, documents):
        merged = []
        for doc in documents or []:
            normalized = self.normalize_document(doc)
            if normalized:
                merged.append(normalized)
        return merged

    def dedupe_documents(self, documents):
        seen = set()
        output = []
        for doc in documents or []:
            key = self._dedupe_key(doc)
            if key not in seen:
                seen.add(key)
                output.append(doc)
        return output

    async def rerank(self, query: str, documents: list):
        query_terms = self._tokenize(query)
        for doc in documents or []:
            doc_terms = self._tokenize(doc.get("content", ""))
            overlap = len(query_terms & doc_terms)
            base_score = self._safe_float(doc.get("score"), default=0.0)
            doc["rerank_score"] = round(base_score + min(overlap * 0.05, 0.4), 4)
        return sorted(documents or [], key=lambda x: x.get("rerank_score", x.get("score", 0)), reverse=True)

    def trim_by_token_budget(self, documents: list, max_tokens: int = 3500):
        selected = []
        used_tokens = 0
        for doc in documents or []:
            token_count = self.estimate_tokens(doc.get("content", ""))
            if selected and used_tokens + token_count > max_tokens:
                break
            selected.append(doc)
            used_tokens += token_count
        return selected

    def normalize_document(self, doc: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(doc, dict):
            return None
        content = str(doc.get("content") or "").strip()
        if not content:
            return None
        normalized = dict(doc)
        normalized["content"] = re.sub(r"\s+", " ", content)
        normalized["score"] = self._safe_float(normalized.get("score"), default=0.5)
        normalized.setdefault("source", normalized.get("url") or normalized.get("file_name"))
        normalized.setdefault("metadata", {})
        return normalized

    def estimate_tokens(self, text: str) -> int:
        return max(1, len(text or "") // 4)

    def _dedupe_key(self, doc: dict[str, Any]) -> str:
        if doc.get("id"):
            return f"id:{doc['id']}"
        source = doc.get("source") or ""
        content = re.sub(r"\s+", " ", doc.get("content", "")).strip().lower()
        return f"content:{source}:{content[:300]}"

    def _tokenize(self, text: str) -> set[str]:
        tokens = re.findall(r"[\wÀ-ỹ]+", (text or "").lower())
        return {token for token in tokens if len(token) > 2}

    def _safe_float(self, value, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

retrieval_service = RetrievalService()
