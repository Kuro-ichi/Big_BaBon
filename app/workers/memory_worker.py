import asyncio

from app.core.config import settings
from app.db.postgres import close_pool
from app.services.llm_service import llm_service
from app.services.persist_service import persist_service
from app.services.retrieval_service import retrieval_service
from app.workers.celery_app import celery_app

@celery_app.task
def extract_user_memory(user_id: str, session_id: str):
    return asyncio.run(_extract_user_memory(user_id, session_id))


async def _extract_user_memory(user_id: str, session_id: str):
    try:
        messages = await persist_service.get_session_messages(session_id, limit=8)
        if not messages:
            return {"user_id": user_id, "session_id": session_id, "status": "skipped", "reason": "no_messages"}

        existing_profile = await persist_service.get_user_profile(user_id)
        profile = await llm_service.extract_profile_fields(messages, existing_profile)
        await persist_service.upsert_user_profile(user_id, profile)

        transcript = "\n".join(
            f"{item.get('role', 'unknown')}: {item.get('content', '')}"
            for item in messages
            if item.get("content")
        )
        memory_id = await retrieval_service.upsert_user_memory(
            user_id=user_id,
            session_id=session_id,
            content=transcript,
            metadata={"message_count": len(messages), "kind": "conversation_window"},
        )
        await persist_service.write_audit_log(
            "user_memory_extracted",
            {
                "memory_id": memory_id,
                "profile_keys": sorted(profile.keys()),
                "collection": settings.QDRANT_MEMORY_COLLECTION,
            },
            user_id=user_id,
            session_id=session_id,
        )
        return {
            "user_id": user_id,
            "session_id": session_id,
            "memory_id": memory_id,
            "profile_keys": sorted(profile.keys()),
            "status": "success",
        }
    finally:
        await close_pool()
