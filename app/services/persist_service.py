import json
import uuid

from app.db.postgres import get_pool, stable_uuid


def _json_value(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value or {}


class PersistService:
    async def save_message(self, session_id: str, user_id: str, role: str, content: str, metadata: dict | None = None):
        user_uuid = stable_uuid(user_id)
        session_uuid = stable_uuid(session_id)
        message_uuid = uuid.uuid4()
        token_count = len((content or "").split())
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)

        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO users (id)
                    VALUES ($1)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    user_uuid,
                )
                await conn.execute(
                    """
                    INSERT INTO sessions (id, user_id)
                    VALUES ($1, $2)
                    ON CONFLICT (id) DO UPDATE SET updated_at = NOW()
                    """,
                    session_uuid,
                    user_uuid,
                )
                await conn.execute(
                    """
                    INSERT INTO messages (id, session_id, user_id, role, content, token_count, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                    """,
                    message_uuid,
                    session_uuid,
                    user_uuid,
                    role,
                    content,
                    token_count,
                    metadata_json,
                )

        return str(message_uuid)

    async def get_session_messages(self, session_id: str, limit: int = 40):
        pool = await get_pool()
        session_uuid = stable_uuid(session_id)
        rows = await pool.fetch(
            """
            SELECT id, role, content, metadata, created_at
            FROM messages
            WHERE session_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            session_uuid,
            limit,
        )
        return [
            {
                "id": str(row["id"]),
                "role": row["role"],
                "content": row["content"],
                "metadata": _json_value(row["metadata"]),
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            }
            for row in reversed(rows)
        ]

    async def count_messages_since_latest_summary(self, session_id: str) -> int:
        pool = await get_pool()
        session_uuid = stable_uuid(session_id)
        row = await pool.fetchrow(
            """
            WITH latest_summary AS (
                SELECT created_at
                FROM session_summaries
                WHERE session_id = $1
                ORDER BY created_at DESC
                LIMIT 1
            )
            SELECT COUNT(*) AS count
            FROM messages
            WHERE session_id = $1
              AND created_at > COALESCE((SELECT created_at FROM latest_summary), 'epoch'::timestamp)
            """,
            session_uuid,
        )
        return int(row["count"]) if row else 0

    async def save_session_summary(self, session_id: str, summary: str, last_message_id: str | None = None):
        pool = await get_pool()
        session_uuid = stable_uuid(session_id)
        summary_uuid = uuid.uuid4()
        last_uuid = stable_uuid(last_message_id) if last_message_id else None
        await pool.execute(
            """
            INSERT INTO session_summaries (id, session_id, summary, last_message_id)
            VALUES ($1, $2, $3, $4)
            """,
            summary_uuid,
            session_uuid,
            summary,
            last_uuid,
        )
        return str(summary_uuid)

    async def get_user_profile(self, user_id: str):
        pool = await get_pool()
        user_uuid = stable_uuid(user_id)
        row = await pool.fetchrow(
            "SELECT profile FROM user_profiles WHERE user_id = $1",
            user_uuid,
        )
        return _json_value(row["profile"]) if row else {}

    async def upsert_user_profile(self, user_id: str, profile: dict):
        user_uuid = stable_uuid(user_id)
        profile_json = json.dumps(profile or {}, ensure_ascii=False)
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO users (id)
                    VALUES ($1)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    user_uuid,
                )
                await conn.execute(
                    """
                    INSERT INTO user_profiles (user_id, profile, updated_at)
                    VALUES ($1, $2::jsonb, NOW())
                    ON CONFLICT (user_id)
                    DO UPDATE SET profile = EXCLUDED.profile, updated_at = NOW()
                    """,
                    user_uuid,
                    profile_json,
                )
        return profile

    async def write_audit_log(self, event_type: str, payload: dict, user_id: str | None = None, session_id: str | None = None, request_id: str | None = None):
        pool = await get_pool()
        await pool.execute(
            """
            INSERT INTO audit_logs (id, user_id, session_id, request_id, event_type, payload)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            """,
            uuid.uuid4(),
            stable_uuid(user_id) if user_id else None,
            stable_uuid(session_id) if session_id else None,
            stable_uuid(request_id) if request_id else None,
            event_type,
            json.dumps(payload or {}, ensure_ascii=False),
        )

persist_service = PersistService()
