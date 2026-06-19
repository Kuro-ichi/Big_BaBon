from app.services.llm_service import llm_service


async def smalltalk_answer_node(state):
    state["answer"] = await llm_service.generate_smalltalk(
        question=state["original_question"],
        runtime_context=state.get("runtime_context", {}),
        token_sink=state.get("token_sink"),
    )
    state["confidence"] = 1.0
    state["trace"].append({"node": "smalltalk_answer", "status": "success"})
    return state


async def direct_answer_node(state):
    state["answer"] = await llm_service.generate_direct_answer(
        question=state["original_question"],
        runtime_context=state.get("runtime_context", {}),
        token_sink=state.get("token_sink"),
    )
    state["confidence"] = 0.75
    state["trace"].append({"node": "direct_answer", "status": "success"})
    return state


async def clarify_response_node(state):
    state["answer"] = "Bạn có thể nói rõ hơn yêu cầu hoặc bổ sung thêm ngữ cảnh không?"
    state["confidence"] = 0.3
    state["trace"].append({"node": "clarify_response", "status": "success"})
    return state


async def safety_response_node(state):
    state["answer"] = "Mình không thể hỗ trợ yêu cầu này theo hướng hiện tại."
    state["confidence"] = 0.2
    state["trace"].append({"node": "safety_response", "status": "success"})
    return state
