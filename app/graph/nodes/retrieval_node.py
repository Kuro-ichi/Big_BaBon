import asyncio
from app.services.retrieval_service import retrieval_service

def _clamp_top_k(value, default, minimum=0, maximum=20):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))

def _clean_filters(filters):
    return {key: value for key, value in filters.items() if value not in (None, "", [])}

async def parallel_retrieval_node(state):
    query = state["rewritten_question"]
    plan = state.get("search_plan", {})
    tasks = []
    task_names = []

    if plan.get("need_kb", True):
        filters = _clean_filters({"domain": plan.get("domain"), "language": plan.get("language", "vi")})
        tasks.append(retrieval_service.search_kb_vector(query, filters, _clamp_top_k(plan.get("top_k_vector"), 8, 1, 12)))
        task_names.append("kb_vector")
        tasks.append(retrieval_service.search_kb_keyword(query, filters, _clamp_top_k(plan.get("top_k_keyword"), 5, 1, 10)))
        task_names.append("kb_keyword")

    if plan.get("need_user_memory", False):
        tasks.append(retrieval_service.search_user_memory(query, state["user_id"], _clamp_top_k(plan.get("top_k_memory"), 3, 0, 5)))
        task_names.append("user_memory")

    results = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []
    documents = []
    source_counts = {}
    for task_name, result in zip(task_names, results):
        if isinstance(result, Exception):
            state["errors"].append({"node": "parallel_retrieval", "source": task_name, "error": str(result)})
        else:
            docs = result or []
            source_counts[task_name] = len(docs)
            for doc in docs:
                doc.setdefault("retrieval_source", task_name)
            documents.extend(docs)

    state["documents"] = documents
    state["metrics"]["retrieval"] = {"source_counts": source_counts, "total": len(documents)}
    state["trace"].append({"node": "parallel_retrieval", "document_count": len(documents), "sources": source_counts})
    return state
