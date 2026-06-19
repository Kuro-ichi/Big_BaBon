import json

from app.db.postgres import get_pool, stable_uuid


def _json_value(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value or {}


class MemoryService:
    async def get_recent_messages(self, session_id: str, limit: int = 8):
        try:
            pool = await get_pool()
            session_uuid = stable_uuid(session_id)
            rows = await pool.fetch(
                """
                SELECT role, content, metadata, created_at
                FROM messages
                WHERE session_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                session_uuid,
                limit,
            )
        except Exception:
            return []
        return [
            {
                "role": row["role"],
                "content": row["content"],
                "metadata": _json_value(row["metadata"]),
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            }
            for row in reversed(rows)
        ]

    async def get_latest_summary(self, session_id: str):
        try:
            pool = await get_pool()
            session_uuid = stable_uuid(session_id)
            row = await pool.fetchrow(
                """
                SELECT summary
                FROM session_summaries
                WHERE session_id = $1
                ORDER BY created_at DESC
                LIMIT 1
                """,
                session_uuid,
            )
        except Exception:
            return ""
        return row["summary"] if row else ""

    async def get_relevant_profile_fields(self, user_id: str, question: str):
        try:
            pool = await get_pool()
            user_uuid = stable_uuid(user_id)
            row = await pool.fetchrow(
                """
                SELECT profile
                FROM user_profiles
                WHERE user_id = $1
                """,
                user_uuid,
            )
        except Exception:
            return {}
        return _json_value(row["profile"]) if row else {}

memory_service = MemoryService()
