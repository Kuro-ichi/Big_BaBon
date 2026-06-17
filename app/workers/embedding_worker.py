import asyncio

from app.db.postgres import close_pool
from app.services.embedding_service import embedding_service
from app.workers.celery_app import celery_app

@celery_app.task
def embed_document(document_id: str, content: str | None = None):
    return asyncio.run(_embed_document(document_id, content))


async def _embed_document(document_id: str, content: str | None):
    try:
        if not content:
            return {
                "document_id": document_id,
                "status": "skipped",
                "reason": "document_registry_not_implemented",
            }
        vector = await embedding_service.embed(content)
        return {"document_id": document_id, "status": "success", "vector_size": len(vector)}
    finally:
        await close_pool()
