from app.workers.celery_app import celery_app
from app.services.runtime_store import runtime_store

@celery_app.task
def summarize_session(session_id: str):
    messages = runtime_store.get_recent_messages(session_id, limit=20)
    if not messages:
        return {"session_id": session_id, "status": "empty"}

    compact_lines = []
    for message in messages[-10:]:
        role = message.get("role", "unknown")
        content = (message.get("content") or "").strip()
        if content:
            compact_lines.append(f"{role}: {content[:240]}")

    summary = "\n".join(compact_lines)
    runtime_store.save_summary(session_id, summary)
    return {"session_id": session_id, "status": "summarized", "message_count": len(messages)}
