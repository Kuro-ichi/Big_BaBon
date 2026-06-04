from app.schemas.chat_schema import ChatRequest
from app.graph.graph_builder import build_chat_graph

class ChatService:
    def __init__(self):
        self.graph = build_chat_graph()

    async def chat(self, request: ChatRequest):
        state = {
            "request_id": request.request_id,
            "user_id": request.user_id,
            "session_id": request.session_id,
            "original_question": request.message,
            "rewritten_question": "",
            "route": "",
            "intent": "",
            "risk_level": "normal",
            "runtime_context": {},
            "search_plan": {},
            "documents": [],
            "selected_context": "",
            "citations": [],
            "answer": "",
            "confidence": 0.0,
            "web_fallback_used": False,
            "errors": [],
            "trace": [],
            "metrics": {},
        }
        result = await self.graph.ainvoke(state)
        return {
            "request_id": result["request_id"],
            "answer": result["answer"],
            "confidence": result["confidence"],
            "route": result["route"],
            "citations": result["citations"],
            "metrics": result["metrics"],
        }

def get_chat_service() -> ChatService:
    return ChatService()
