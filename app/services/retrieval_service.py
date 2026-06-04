class RetrievalService:
    async def search_kb_vector(self, query: str, filters: dict, top_k: int = 8):
        return []

    async def search_kb_keyword(self, query: str, filters: dict, top_k: int = 5):
        return []

    async def search_user_memory(self, query: str, user_id: str, top_k: int = 3):
        # Bắt buộc filter user_id khi triển khai thật.
        return []

    def merge_documents(self, documents):
        return documents

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

    def trim_by_token_budget(self, documents: list, max_tokens: int = 3500):
        return documents[:8]

retrieval_service = RetrievalService()
