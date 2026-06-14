from app.services.llm_service import llm_service
from app.services.persist_service import persist_service

async def answer_generation_node(state):
    try:
        state["answer"] = await llm_service.generate_answer(
            question=state["original_question"],
            rewritten_question=state["rewritten_question"],
            runtime_context=state["runtime_context"],
            selected_context=state["selected_context"],
            citations=state["citations"],
        )
        state["trace"].append({"node": "answer_generation", "status": "success"})
    except Exception as exc:
        state["answer"] = "Mình chưa thể tạo câu trả lời ở lượt này. Bạn vui lòng thử lại hoặc bổ sung thêm ngữ cảnh."
        state["confidence"] = 0.0
        state["errors"].append({"node": "answer_generation", "error": str(exc)})
        state["trace"].append({"node": "answer_generation", "status": "failed"})
    return state

async def persist_async_node(state):
    try:
        await persist_service.save_message(state["session_id"], state["user_id"], "user", state["original_question"])
        await persist_service.save_message(
            state["session_id"], state["user_id"], "assistant", state["answer"],
            metadata={
                "citations": state["citations"],
                "confidence": state["confidence"],
                "route": state.get("route"),
                "intent": state.get("intent"),
                "trace": state["trace"],
                "errors": state["errors"],
            },
        )
        state["metrics"]["persisted"] = True
    except Exception as exc:
        state["metrics"]["persisted"] = False
        state["errors"].append({"node": "persist_async", "error": str(exc)})
    state["metrics"]["trace_length"] = len(state["trace"])
    state["metrics"]["error_count"] = len(state["errors"])
    return state
