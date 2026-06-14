from app.services.llm_service import llm_service

async def smart_precheck_node(state):
    try:
        precheck = await llm_service.smart_precheck(
            question=state["original_question"],
            runtime_context=state["runtime_context"],
        )
    except Exception as exc:
        precheck = {
            "route": "rag",
            "intent": "knowledge_lookup",
            "risk_level": "normal",
            "rewritten_query": state["original_question"],
            "search_plan": {
                "need_kb": True,
                "need_user_memory": False,
                "need_web": False,
                "domain": None,
                "language": state.get("runtime_context", {}).get("language", "vi"),
                "top_k_vector": 8,
                "top_k_keyword": 5,
                "top_k_memory": 3,
            },
        }
        state["errors"].append({"node": "smart_precheck", "error": str(exc)})

    state["route"] = precheck.get("route", "rag")
    state["intent"] = precheck.get("intent", "")
    state["risk_level"] = precheck.get("risk_level", "normal")
    state["rewritten_question"] = precheck.get("rewritten_query", state["original_question"])
    state["search_plan"] = precheck.get("search_plan", {})
    state["metrics"]["precheck"] = {
        "intent": state["intent"],
        "risk_level": state["risk_level"],
        "needs_clarification": precheck.get("needs_clarification", False),
        "prompt_meta": precheck.get("prompt_meta"),
    }
    state["trace"].append({"node": "smart_precheck", "route": state["route"], "intent": state["intent"]})
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
