from app.workers.celery_app import celery_app

@celery_app.task
def extract_user_memory(user_id: str, session_id: str):
    return {"user_id": user_id, "session_id": session_id, "status": "queued"}
