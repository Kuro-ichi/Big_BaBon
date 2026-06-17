import asyncio
from app.services.retrieval_service import retrieval_service

async def parallel_retrieval_node(state):
    query = state["rewritten_question"]
    plan = state.get("search_plan", {})
    tasks = []

    if plan.get("need_kb", True):
        filters = {
            "domain": plan.get("domain"),
            "language": plan.get("language", "vi"),
            "preferred_source_types": plan.get("preferred_source_types"),
            "source_type": plan.get("source_type"),
            "risk_level": plan.get("risk_level"),
            "condition": plan.get("condition"),
        }
        tasks.append(retrieval_service.search_kb_vector(query, filters, plan.get("top_k_vector", 8)))
        tasks.append(retrieval_service.search_kb_keyword(query, filters, plan.get("top_k_keyword", 5)))

    if plan.get("need_user_memory", False):
        tasks.append(retrieval_service.search_user_memory(query, state["user_id"], plan.get("top_k_memory", 3)))

    results = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []
    documents = []
    for result in results:
        if isinstance(result, Exception):
            state["errors"].append({"node": "parallel_retrieval", "error": str(result)})
        else:
            documents.extend(result)

    state["documents"] = documents
    state["trace"].append({"node": "parallel_retrieval", "document_count": len(documents)})
    return state
