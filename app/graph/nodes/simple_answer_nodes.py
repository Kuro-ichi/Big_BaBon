from app.services.llm_service import llm_service


async def smalltalk_answer_node(state):
    state["answer"] = await llm_service.generate_simple_answer(
        "smalltalk",
        state["original_question"],
        state.get("runtime_context", {}),
    )
    state["confidence"] = 1.0
    state["trace"].append({"node": "smalltalk_answer", "status": "success"})
    return state

async def direct_answer_node(state):
    state["answer"] = await llm_service.generate_simple_answer(
        "direct_answer",
        state["original_question"],
        state.get("runtime_context", {}),
    )
    state["confidence"] = 0.8
    state["trace"].append({"node": "direct_answer", "status": "success"})
    return state

async def clarify_response_node(state):
    state["answer"] = await llm_service.generate_simple_answer(
        "clarify",
        state["original_question"],
        state.get("runtime_context", {}),
    )
    state["confidence"] = 0.3
    state["trace"].append({"node": "clarify_response", "status": "success"})
    return state

async def safety_response_node(state):
    state["answer"] = await llm_service.generate_simple_answer(
        "safety",
        state["original_question"],
        state.get("runtime_context", {}),
    )
    state["confidence"] = 0.2
    state["trace"].append({"node": "safety_response", "status": "success"})
    return state
