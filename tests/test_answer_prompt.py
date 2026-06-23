import unittest
from unittest.mock import AsyncMock

from app.services.llm_service import LLMService
from app.graph.nodes.smart_precheck_node import _is_direct_technical_question


class AnswerPromptTests(unittest.IsolatedAsyncioTestCase):
    def test_api_followup_is_direct_when_session_has_technical_context(self):
        runtime_context = {
            "recent_messages": [
                {"role": "user", "content": "Tôi test POST /v1/orders, status 201."},
            ]
        }

        self.assertTrue(
            _is_direct_technical_question("Tóm tắt test đã thống nhất.", runtime_context)
        )

    async def test_direct_answer_rewrites_chinese_before_emitting(self):
        service = LLMService()
        service._provider = "ollama"
        service._chat = AsyncMock(side_effect=["Status 成功: 204", "Status thành công: 204"])
        sink = AsyncMock()

        answer = await service.generate_direct_answer(
            "Status là gì?",
            {"recent_messages": []},
            token_sink=sink,
        )

        self.assertEqual(answer, "Status thành công: 204")
        self.assertEqual(service._chat.await_count, 2)
        sink.assert_awaited_once_with("Status thành công: 204")

    async def test_generate_answer_uses_all_supplied_context(self):
        service = LLMService()
        service._provider = "ollama"
        service._chat = AsyncMock(return_value="Câu trả lời [1]")

        answer = await service.generate_answer(
            question="Còn tôi thì sao?",
            rewritten_question="Người dùng bị tiểu đường nên ăn gì?",
            runtime_context={
                "session_summary": "Người dùng bị tiểu đường type 2.",
                "recent_messages": [
                    {"role": "user", "content": "Tôi muốn giảm đường."},
                    {"role": "assistant", "content": "Hãy ưu tiên thực phẩm giàu chất xơ."},
                ],
            },
            selected_context="[1] Hướng dẫn\nNội dung y khoa.",
            citations=[{
                "reference_id": 1,
                "title": "Hướng dẫn",
                "source_type": "clinical_nutrition_guideline",
                "source": "https://example.test/guideline",
            }],
        )

        self.assertEqual(answer, "Câu trả lời [1]")
        messages = service._chat.await_args.args[1]
        prompt = messages[1]["content"]
        self.assertIn("Còn tôi thì sao?", prompt)
        self.assertIn("Người dùng bị tiểu đường nên ăn gì?", prompt)
        self.assertIn("Người dùng bị tiểu đường type 2.", prompt)
        self.assertIn("user: Tôi muốn giảm đường.", prompt)
        self.assertIn("[1] Hướng dẫn", prompt)
        self.assertIn("https://example.test/guideline", prompt)

    def test_runtime_context_is_bounded(self):
        service = LLMService()
        recent = [
            {"role": "user", "content": str(index) + "x" * 1000}
            for index in range(10)
        ]

        formatted = service._format_runtime_context({"recent_messages": recent})

        self.assertNotIn("0xxx", formatted)
        self.assertNotIn("1xxx", formatted)
        self.assertIn("2xxx", formatted)
        self.assertIn("9xxx", formatted)
        self.assertLessEqual(max(len(line.split(": ", 1)[1]) for line in formatted.splitlines()), 300)

    def test_session_summary_is_bounded(self):
        service = LLMService()

        formatted = service._format_session_summary({"session_summary": "x" * 1200})

        self.assertEqual(len(formatted), 800)


if __name__ == "__main__":
    unittest.main()
