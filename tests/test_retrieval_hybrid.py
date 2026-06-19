import unittest

from app.services.retrieval_service import RetrievalService


class RetrievalHybridTests(unittest.TestCase):
    def setUp(self):
        self.service = RetrievalService()

    def test_sparse_vector_is_stable_sorted_and_has_bigrams(self):
        first = self.service._sparse_vector("Suy thận suy thận ăn gì")
        second = self.service._sparse_vector("Suy thận suy thận ăn gì")

        self.assertEqual(first, second)
        self.assertEqual(first.indices, sorted(first.indices))
        self.assertGreater(len(first.indices), len(self.service._tokens("suy thận ăn gì")))

    def test_local_rrf_rewards_documents_returned_by_both_retrievers(self):
        async def run():
            async def dense(*_args, **_kwargs):
                return [{"id": "both", "score": 0.9}, {"id": "dense", "score": 0.8}]

            async def keyword(*_args, **_kwargs):
                return [{"id": "both", "score": 1.0}, {"id": "keyword", "score": 0.8}]

            self.service.search_kb_vector = dense
            self.service.search_kb_keyword = keyword
            return await self.service._search_kb_legacy("query", {}, 3, 3)

        import asyncio

        ranked = asyncio.run(run())
        self.assertEqual(ranked[0]["id"], "both")
        self.assertEqual(ranked[0]["matched_retrievers"], ["dense", "keyword"])
        self.assertEqual(ranked[0]["retrieval_method"], "local_rrf_fallback")

    def test_rerank_normalizes_rrf_scores(self):
        documents = [
            {"id": "a", "score": 0.02, "content": "không liên quan", "metadata": {}},
            {"id": "b", "score": 0.01, "content": "không liên quan", "metadata": {}},
        ]

        import asyncio

        ranked = asyncio.run(self.service.rerank_with_plan("truy vấn", documents, {}))
        by_id = {doc["id"]: doc for doc in ranked}
        self.assertEqual(by_id["a"]["normalized_retrieval_score"], 1.0)
        self.assertEqual(by_id["b"]["normalized_retrieval_score"], 0.5)
        self.assertGreater(by_id["a"]["rerank_score"], by_id["b"]["rerank_score"])


if __name__ == "__main__":
    unittest.main()
