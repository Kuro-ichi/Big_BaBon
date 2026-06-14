from app.services.retrieval_service import retrieval_service

def format_context(docs):
    blocks = []
    for index, doc in enumerate(docs or [], start=1):
        title = doc.get("title") or doc.get("source") or doc.get("id") or "unknown source"
        content = doc.get("content", "")
        blocks.append(f"[{index}] {title}\n{content}")
    return "\n\n".join(blocks)

def extract_citations(docs):
    citations = []
    for index, doc in enumerate(docs or [], start=1):
        source = doc.get("source") or doc.get("url") or doc.get("file_name")
        if not source and not doc.get("id"):
            continue
        citations.append(
            {
                "index": index,
                "id": doc.get("id"),
                "source": source,
                "title": doc.get("title"),
                "score": doc.get("rerank_score", doc.get("score")),
                "retrieval_source": doc.get("retrieval_source"),
            }
        )
    return citations

async def rerank_trim_node(state):
    merged = retrieval_service.merge_documents(state["documents"])
    deduped = retrieval_service.dedupe_documents(merged)
    reranked = await retrieval_service.rerank(state["rewritten_question"], deduped)
    selected_docs = retrieval_service.trim_by_token_budget(reranked, max_tokens=3500)
    state["selected_context"] = format_context(selected_docs)
    state["citations"] = extract_citations(selected_docs)
    state["metrics"]["context"] = {
        "merged_count": len(merged),
        "deduped_count": len(deduped),
        "selected_count": len(selected_docs),
        "estimated_tokens": retrieval_service.estimate_tokens(state["selected_context"]),
    }
    state["trace"].append({"node": "rerank_trim", "before": len(state["documents"]), "after": len(selected_docs)})
    return state
