from app.services.retrieval_service import retrieval_service

def format_context(docs):
    return "\n\n".join([doc.get("content", "") for doc in docs])

def extract_citations(docs):
    return [{"id": doc.get("id"), "source": doc.get("source")} for doc in docs if doc.get("source")]

async def rerank_trim_node(state):
    merged = retrieval_service.merge_documents(state["documents"])
    deduped = retrieval_service.dedupe_documents(merged)
    reranked = await retrieval_service.rerank(state["rewritten_question"], deduped)
    selected_docs = retrieval_service.trim_by_token_budget(reranked, max_tokens=3500)
    state["selected_context"] = format_context(selected_docs)
    state["citations"] = extract_citations(selected_docs)
    state["trace"].append({"node": "rerank_trim", "before": len(state["documents"]), "after": len(selected_docs)})
    return state
