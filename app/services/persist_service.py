from app.services.runtime_store import runtime_store


class PersistService:
    async def save_message(self, session_id: str, user_id: str, role: str, content: str, metadata: dict | None = None):
        return runtime_store.save_message(
            session_id=session_id,
            user_id=user_id,
            role=role,
            content=content,
            metadata=metadata,
        )

persist_service = PersistService()
