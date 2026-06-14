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
            "runtime_context": {"language": request.language or "vi"},
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
            "request_id": result.get("request_id", request.request_id),
            "answer": result.get("answer", ""),
            "confidence": result.get("confidence", 0.0),
            "route": result.get("route", ""),
            "citations": result.get("citations", []),
            "metrics": result.get("metrics", {}),
        }

    async def chat_stream(self, request: ChatRequest):
        return await self.chat(request)

def get_chat_service() -> ChatService:
    return ChatService()
