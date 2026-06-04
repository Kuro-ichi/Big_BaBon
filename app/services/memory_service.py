class MemoryService:
    async def get_recent_messages(self, session_id: str, limit: int = 8):
        return []

    async def get_latest_summary(self, session_id: str):
        return ""

    async def get_relevant_profile_fields(self, user_id: str, question: str):
        return {}

memory_service = MemoryService()
