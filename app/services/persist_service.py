class PersistService:
    async def save_message(self, session_id: str, user_id: str, role: str, content: str, metadata: dict | None = None):
        return None

persist_service = PersistService()
