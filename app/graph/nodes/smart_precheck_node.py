from app.services.llm_service import llm_service

async def smart_precheck_node(state):
    precheck = await llm_service.smart_precheck(
        question=state["original_question"],
        runtime_context=state["runtime_context"],
    )
    state["route"] = precheck.get("route", "rag")
    state["risk_level"] = precheck.get("risk_level", "normal")
    state["rewritten_question"] = precheck.get("rewritten_query", state["original_question"])
    state["search_plan"] = precheck.get("search_plan", {})
    state["trace"].append({"node": "smart_precheck", "route": state["route"]})
    return state

def route_after_precheck(state):
    route = state.get("route")
    if route == "smalltalk":
        return "smalltalk_answer"
    if route == "direct_answer":
        return "direct_answer"
    if route == "clarify":
        return "clarify_response"
    if route == "safety":
        return "safety_response"
    return "parallel_retrieval"
