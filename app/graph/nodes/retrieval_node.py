import asyncio
from app.services.retrieval_service import retrieval_service


async def parallel_retrieval_node(state):
    query = state.get("rewritten_question") or state.get("query") or ""
    plan = state.get("search_plan", {})

    state.setdefault("errors", [])
    state.setdefault("trace", [])

    tasks = []

    filters = {
        "domain": plan.get("domain"),
        "language": plan.get("language", "vi"),
        "preferred_source_types": plan.get("preferred_source_types"),
        "source_type": plan.get("source_type"),
        "risk_level": plan.get("risk_level"),
        "condition": plan.get("condition"),
    }

    if plan.get("need_kb", True):
        top_k_vector = int(plan.get("top_k_vector", 8) or 0)
        top_k_keyword = int(plan.get("top_k_keyword", 5) or 0)

        if top_k_vector > 0 or top_k_keyword > 0:
            tasks.append(
                retrieval_service.search_kb_hybrid(
                    query,
                    filters,
                    top_k=max(top_k_vector, top_k_keyword, 1),
                    dense_limit=max(top_k_vector, 1),
                    sparse_limit=max(top_k_keyword, 1),
                )
            )

    if plan.get("need_user_memory", False):
        tasks.append(
            retrieval_service.search_user_memory(
                query,
                state.get("user_id"),
                plan.get("top_k_memory", 3),
            )
        )

    results = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []

    documents = []

    for result in results:
        if isinstance(result, Exception):
            state["errors"].append({
                "node": "parallel_retrieval",
                "error": str(result),
            })
            continue

        if result is None:
            continue

        if isinstance(result, list):
            documents.extend(result)
        elif isinstance(result, tuple):
            documents.extend(list(result))
        elif isinstance(result, dict):
            if "documents" in result and isinstance(result["documents"], list):
                documents.extend(result["documents"])
            elif "results" in result and isinstance(result["results"], list):
                documents.extend(result["results"])
            else:
                documents.append(result)
        else:
            documents.append(result)

    state["documents"] = documents
    state["trace"].append({
        "node": "parallel_retrieval",
        "document_count": len(documents),
        "task_count": len(tasks),
    })

    return state
