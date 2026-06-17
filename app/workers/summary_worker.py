import asyncio

from app.core.config import settings
from app.db.postgres import close_pool
from app.services.llm_service import llm_service
from app.services.persist_service import persist_service
from app.workers.celery_app import celery_app

@celery_app.task
def summarize_session(session_id: str):
    return asyncio.run(_summarize_session(session_id))


async def _summarize_session(session_id: str):
    try:
        messages = await persist_service.get_session_messages(
            session_id,
            limit=settings.SUMMARY_RECENT_MESSAGE_LIMIT,
        )
        if not messages:
            return {"session_id": session_id, "status": "skipped", "reason": "no_messages"}

        summary = await llm_service.summarize_session(messages)
        if not summary:
            return {"session_id": session_id, "status": "skipped", "reason": "empty_summary"}

        last_message_id = messages[-1]["id"]
        summary_id = await persist_service.save_session_summary(session_id, summary, last_message_id)
        await persist_service.write_audit_log(
            "session_summary_created",
            {"summary_id": summary_id, "message_count": len(messages)},
            session_id=session_id,
        )
        return {"session_id": session_id, "summary_id": summary_id, "status": "success"}
    finally:
        await close_pool()
