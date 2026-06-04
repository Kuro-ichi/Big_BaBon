from app.workers.celery_app import celery_app

@celery_app.task
def summarize_session(session_id: str):
    return {"session_id": session_id, "status": "queued"}
