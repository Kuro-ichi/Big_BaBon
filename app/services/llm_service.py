class LLMService:
    async def smart_precheck(self, question: str, runtime_context: dict):
        q = question.lower().strip()
        if q in ["hi", "hello", "xin chào", "chào"]:
            return {"route": "smalltalk", "risk_level": "normal", "rewritten_query": question, "search_plan": {}}
        return {
            "route": "rag",
            "risk_level": "normal",
            "needs_clarification": False,
            "rewritten_query": question,
            "search_plan": {
                "need_kb": True,
                "need_user_memory": False,
                "need_web": False,
                "domain": None,
                "language": "vi",
                "top_k_vector": 8,
                "top_k_keyword": 5,
                "top_k_memory": 3,
            },
        }

    async def generate_answer(self, question: str, rewritten_question: str, runtime_context: dict, selected_context: str, citations: list):
        if not selected_context:
            return "Mình chưa tìm thấy đủ context trong knowledge base để trả lời chắc chắn. Bạn cần thêm tài liệu hoặc bật web fallback cho câu hỏi này."
        return f"Dựa trên context đã truy xuất, câu hỏi của bạn là: {question}\n\nContext:\n{selected_context[:1200]}"

llm_service = LLMService()
