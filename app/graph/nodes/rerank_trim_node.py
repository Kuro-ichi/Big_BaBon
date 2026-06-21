from app.services.retrieval_service import retrieval_service
from app.core.config import settings

def format_context(docs):
    blocks = []
    for index, doc in enumerate(docs, start=1):
        metadata = doc.get("metadata", {}) or {}
        title = metadata.get("title") or metadata.get("food_name") or "Tài liệu"
        blocks.append(f"[{index}] {title}\n{doc.get('content', '')}")
    return "\n\n".join(blocks)

def extract_citations(docs):
    citations = []
    for index, doc in enumerate(docs, start=1):
        if not doc.get("source"):
            continue
        metadata = doc.get("metadata", {}) or {}
        citations.append({
            "reference_id": index,
            "id": doc.get("id"),
            "source": doc.get("source"),
            "title": metadata.get("title"),
            "source_type": metadata.get("source_type"),
            "score": doc.get("score"),
        })
    return citations

async def rerank_trim_node(state):
    deduped = retrieval_service.dedupe_documents(state["documents"])
    reranked = await retrieval_service.rerank_with_plan(state["rewritten_question"], deduped, state.get("search_plan", {}))
    selected_docs = retrieval_service.trim_by_token_budget(
        reranked,
        max_tokens=settings.RETRIEVAL_CONTEXT_MAX_TOKENS,
        max_documents=settings.RETRIEVAL_MAX_DOCUMENTS,
        min_score=settings.RETRIEVAL_MIN_RERANK_SCORE,
    )
    # Các node phía sau phải dùng score đã normalize/rerank, không dùng lại
    # RRF score thô (~0.01-0.03) từ parallel retrieval để tính confidence.
    state["documents"] = selected_docs
    state["selected_context"] = format_context(selected_docs)
    state["citations"] = extract_citations(selected_docs)
    state["metrics"]["answer_subject"] = retrieval_service.extract_subject(
        state["original_question"],
        selected_docs,
    )
    state["metrics"]["context"] = {
        "documents": len(selected_docs),
        "characters": len(state["selected_context"]),
        "max_tokens": settings.RETRIEVAL_CONTEXT_MAX_TOKENS,
    }
    state["metrics"]["top_context"] = [
        {
            "title": (doc.get("metadata", {}) or {}).get("title"),
            "source_type": (doc.get("metadata", {}) or {}).get("source_type"),
            "score": doc.get("score"),
            "original_score": doc.get("original_score"),
            "normalized_retrieval_score": doc.get("normalized_retrieval_score"),
            "retrieval_method": doc.get("retrieval_method"),
            "fusion_rank": doc.get("fusion_rank"),
        }
        for doc in selected_docs[:5]
    ]
    state["trace"].append({"node": "rerank_trim", "before": len(state["documents"]), "after": len(selected_docs)})
    return state
