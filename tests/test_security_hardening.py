import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import jwt

from app.core.config import settings
from app.graph.nodes.context_guard_nodes import (
    EMPTY_ANSWER_FALLBACK,
    UNSAFE_ANSWER_FALLBACK,
    lightweight_guard_node,
)
from app.services.auth_service import create_access_token, decode_access_token
from app.services.retrieval_service import RetrievalService


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.original_secret = settings.JWT_SECRET
        settings.JWT_SECRET = "test-only-secret-that-is-longer-than-32-characters"

    def tearDown(self):
        settings.JWT_SECRET = self.original_secret

    def test_token_round_trip_uses_subject_as_identity(self):
        token = create_access_token("client-a", expires_minutes=5)
        self.assertEqual(decode_access_token(token).user_id, "client-a")

    def test_token_signed_with_another_secret_is_rejected(self):
        token = jwt.encode(
            {"sub": "attacker"},
            "another-secret-that-is-longer-than-32-characters",
            algorithm="HS256",
        )
        with self.assertRaises(jwt.PyJWTError):
            decode_access_token(token)


class RetrievalFilterTests(unittest.IsolatedAsyncioTestCase):
    def test_condition_is_a_hard_qdrant_filter(self):
        service = RetrievalService()
        query_filter = service._build_qdrant_filter({"condition": ["CKD"]})
        dumped = query_filter.model_dump()
        condition = next(item for item in dumped["must"] if item["key"] == "metadata.condition")
        self.assertEqual(condition["match"]["any"], ["ckd"])
        self.assertFalse(service._doc_matches_filters({"metadata": {}}, {"condition": ["ckd"]}))
        self.assertTrue(
            service._doc_matches_filters(
                {"metadata": {"condition": ["ckd", "general"]}},
                {"condition": ["ckd"]},
            )
        )

    async def test_filtered_vector_failure_does_not_retry_without_filter(self):
        service = RetrievalService()
        client = SimpleNamespace(
            get_collection=AsyncMock(
                return_value=SimpleNamespace(
                    config=SimpleNamespace(params=SimpleNamespace(vectors={"": object()}))
                )
            ),
            search=AsyncMock(side_effect=RuntimeError("filter failure")),
        )
        service._client = client
        service._client_loop = asyncio.get_running_loop()

        with (
            patch("app.services.retrieval_service.cache_service.get_json", AsyncMock(return_value=None)),
            patch("app.services.retrieval_service.embedding_service.embed", AsyncMock(return_value=[0.1, 0.2])),
        ):
            with self.assertRaises(RuntimeError):
                await service.search_kb_vector("query", {"condition": ["ckd"]}, 3)

        client.search.assert_awaited_once()
        self.assertIsNotNone(client.search.await_args.kwargs["query_filter"])


class OutputGuardTests(unittest.TestCase):
    def _state(self, answer):
        return {
            "answer": answer,
            "risk_level": "sensitive",
            "confidence": 0.9,
            "citations": [{"id": "source"}],
            "errors": [],
            "metrics": {},
            "trace": [],
        }

    def test_unsafe_answer_is_replaced(self):
        state = lightweight_guard_node(self._state("Bạn nên bỏ insulin ngay hôm nay."))
        self.assertEqual(state["answer"], UNSAFE_ANSWER_FALLBACK)
        self.assertEqual(state["confidence"], 0.0)
        self.assertEqual(state["citations"], [])
        self.assertTrue(state["metrics"]["guard_replaced_answer"])

    def test_empty_answer_is_replaced(self):
        state = lightweight_guard_node(self._state(""))
        self.assertEqual(state["answer"], EMPTY_ANSWER_FALLBACK)

    def test_negated_unsafe_phrase_is_allowed(self):
        state = lightweight_guard_node(self._state("Bạn không nên bỏ insulin."))
        self.assertEqual(state["answer"], "Bạn không nên bỏ insulin.")
        self.assertFalse(state["metrics"]["guard_replaced_answer"])

    def test_curated_safety_fast_path_is_not_rejected(self):
        state = self._state("Bạn không nên dùng muối kali, nhịn ăn hoặc detox.")
        state["safety_fast_path"] = True
        state["safety_action"] = "respond"

        guarded = lightweight_guard_node(state)

        self.assertEqual(guarded["answer"], "Bạn không nên dùng muối kali, nhịn ăn hoặc detox.")
        self.assertFalse(guarded["metrics"]["guard_replaced_answer"])


if __name__ == "__main__":
    unittest.main()
