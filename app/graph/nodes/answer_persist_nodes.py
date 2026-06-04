from app.services.llm_service import llm_service
from app.services.persist_service import persist_service

async def answer_generation_node(state):
    state["answer"] = await llm_service.generate_answer(
        question=state["original_question"],
        rewritten_question=state["rewritten_question"],
        runtime_context=state["runtime_context"],
        selected_context=state["selected_context"],
        citations=state["citations"],
    )
    state["trace"].append({"node": "answer_generation", "status": "success"})
    return state

async def persist_async_node(state):
    await persist_service.save_message(state["session_id"], state["user_id"], "user", state["original_question"])
    await persist_service.save_message(
        state["session_id"], state["user_id"], "assistant", state["answer"],
        metadata={"citations": state["citations"], "confidence": state["confidence"], "trace": state["trace"]},
    )
    state["metrics"]["trace_length"] = len(state["trace"])
    return state
