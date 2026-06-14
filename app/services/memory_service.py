from app.services.runtime_store import runtime_store


class MemoryService:
    async def get_recent_messages(self, session_id: str, limit: int = 8):
        return runtime_store.get_recent_messages(session_id, limit=limit)

    async def get_latest_summary(self, session_id: str):
        return runtime_store.get_latest_summary(session_id)

    async def get_relevant_profile_fields(self, user_id: str, question: str):
        profile = runtime_store.get_user_profile(user_id)
        if not profile:
            return {}

        question_lower = (question or "").lower()
        relevant = {}
        for key, value in profile.items():
            if key.lower() in question_lower or len(relevant) < 5:
                relevant[key] = value
        return relevant

memory_service = MemoryService()
