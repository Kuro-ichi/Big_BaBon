from app.services.web_search_service import web_search_service


async def web_fallback_node(state):
    query = state.get("rewritten_question") or state.get("original_question")
    top_k = state.get("search_plan", {}).get("top_k_web", 5)
    docs = await web_search_service.search_web(query, max_results=top_k)
    state["web_fallback_used"] = True

    if docs:
        state["documents"] = state.get("documents", []) + docs
    state["trace"].append({"node": "web_fallback", "document_count": len(docs)})
    state["metrics"]["web_fallback_document_count"] = len(docs)
    return state
