from app.workers.celery_app import celery_app

@celery_app.task
def embed_document(document_id: str):
    return {"document_id": document_id, "status": "queued"}
