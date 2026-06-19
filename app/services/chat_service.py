import asyncio
import time

from app.schemas.chat_schema import ChatRequest
from app.graph.graph_builder import build_chat_graph
from app.services.persist_service import persist_service

class ChatService:
    def __init__(self):
        self.graph = build_chat_graph()

    def _build_state(self, request: ChatRequest, token_sink=None):
        return {
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
            "token_sink": token_sink,
        }

    @staticmethod
    def _response(result):
        return {
            "request_id": result["request_id"],
            "answer": result["answer"],
            "confidence": result["confidence"],
            "route": result["route"],
            "citations": result["citations"],
            "metrics": result["metrics"],
        }

    async def ensure_session_access(self, request: ChatRequest) -> None:
        if not request.user_id:
            raise PermissionError("Authenticated user_id is required")
        await persist_service.ensure_session_owner(request.session_id, request.user_id)

    async def chat(self, request: ChatRequest):
        await self.ensure_session_access(request)
        state = self._build_state(request)
        started = time.perf_counter()
        result = await self.graph.ainvoke(state)
        result.setdefault("metrics", {})["total_latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return self._response(result)

    async def chat_stream(self, request: ChatRequest, access_checked: bool = False):
        if not access_checked:
            await self.ensure_session_access(request)
        queue = asyncio.Queue()
        started = time.perf_counter()
        emitted = False

        async def token_sink(content: str):
            await queue.put(content)

        state = self._build_state(request, token_sink=token_sink)
        graph_task = asyncio.create_task(self.graph.ainvoke(state))

        try:
            while not graph_task.done():
                try:
                    content = await asyncio.wait_for(queue.get(), timeout=0.05)
                except asyncio.TimeoutError:
                    continue
                emitted = True
                yield {
                    "type": "token",
                    "content": content,
                    "request_id": request.request_id,
                }

            while not queue.empty():
                emitted = True
                yield {
                    "type": "token",
                    "content": queue.get_nowait(),
                    "request_id": request.request_id,
                }

            result = await graph_task
            result.setdefault("metrics", {})["total_latency_ms"] = round(
                (time.perf_counter() - started) * 1000,
                2,
            )

            # Static safety/clarification/fallback answers do not call Ollama.
            if not emitted and result.get("answer"):
                yield {
                    "type": "token",
                    "content": result["answer"],
                    "request_id": result["request_id"],
                }

            yield {
                "type": "done",
                "request_id": result["request_id"],
                "route": result.get("route"),
                "confidence": result.get("confidence"),
                "citations": result.get("citations", []),
                "metrics": result.get("metrics", {}),
            }
        except asyncio.CancelledError:
            graph_task.cancel()
            raise
        except Exception as exc:
            yield {
                "type": "error",
                "request_id": request.request_id,
                "message": str(exc),
            }
        finally:
            if not graph_task.done():
                graph_task.cancel()

def get_chat_service() -> ChatService:
    return ChatService()
    
