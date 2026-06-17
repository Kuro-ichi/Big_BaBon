import time

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
            "safety_action": "pass",
            "safety_condition": "",
            "safety_response_kind": "",
            "safety_fast_path": False,
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
        started = time.perf_counter()
        result = await self.graph.ainvoke(state)
        result.setdefault("metrics", {})["total_latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return {
            "request_id": result["request_id"],
            "answer": result["answer"],
            "confidence": result["confidence"],
            "route": result["route"],
            "citations": result["citations"],
            "metrics": result["metrics"],
        }
    async def chat_stream(self, request: ChatRequest):
        return await self.chat(request)

def get_chat_service() -> ChatService:
    return ChatService()
    
