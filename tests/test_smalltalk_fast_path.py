import unittest
from unittest.mock import AsyncMock, patch

from app.services.llm_service import DEFAULT_GREETING_ANSWER, LLMService


class SmalltalkFastPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_extended_vietnamese_greeting_skips_router_model(self):
        service = LLMService()
        service._chat = AsyncMock(side_effect=AssertionError("Không được gọi model"))

        result = await service.smart_precheck("Xin chào bạn giúp được gì?", {})

        self.assertEqual(result["route"], "smalltalk")
        service._chat.assert_not_awaited()

    async def test_extended_vietnamese_greeting_has_fixed_answer(self):
        service = LLMService()
        service._chat = AsyncMock(side_effect=AssertionError("Không được gọi model"))

        answer = await service.generate_smalltalk("Xin chào bạn giúp được gì?", {})

        self.assertEqual(answer, DEFAULT_GREETING_ANSWER)
        service._chat.assert_not_awaited()

    async def test_common_greeting_variants_use_fast_path(self):
        service = LLMService()

        for question in (
            "Hey bot ơi!",
            "Chào trợ lý nhé",
            "Bạn hỗ trợ mình được gì?",
            "Hello, bạn có thể làm được gì?",
        ):
            with self.subTest(question=question):
                self.assertEqual(
                    service._simple_greeting_answer(question),
                    DEFAULT_GREETING_ANSWER,
                )

    async def test_greeting_with_real_question_does_not_use_fast_path(self):
        service = LLMService()

        answer = service._simple_greeting_answer(
            "Xin chào, phở bò có bao nhiêu calo?"
        )

        self.assertIsNone(answer)

    async def test_chinese_output_is_replaced_before_streaming(self):
        service = LLMService()
        sink = AsyncMock()
        with patch.object(type(service), "_use_local", new_callable=lambda: property(lambda _: True)):
            service._chat = AsyncMock(return_value="你好，我能帮助你。")
            answer = await service.generate_smalltalk("Cảm ơn nhé", {}, token_sink=sink)

        self.assertEqual(answer, DEFAULT_GREETING_ANSWER)
        sink.assert_awaited_once_with(DEFAULT_GREETING_ANSWER)


if __name__ == "__main__":
    unittest.main()
