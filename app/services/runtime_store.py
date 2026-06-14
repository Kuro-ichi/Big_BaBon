from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


class RuntimeStore:
    """Small in-process store used when external persistence is not wired yet."""

    def __init__(self) -> None:
        self._messages: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=200))
        self._session_summaries: dict[str, str] = {}
        self._user_profiles: dict[str, dict[str, Any]] = {}

    def save_message(
        self,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        message = {
            "id": str(uuid4()),
            "session_id": session_id,
            "user_id": user_id,
            "role": role,
            "content": content,
            "metadata": metadata or {},
            "token_count": self.estimate_tokens(content),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._messages[session_id].append(message)
        return message

    def get_recent_messages(self, session_id: str, limit: int = 8) -> list[dict[str, Any]]:
        limit = max(0, min(int(limit or 0), 50))
        messages = list(self._messages.get(session_id, []))
        return messages[-limit:] if limit else []

    def get_latest_summary(self, session_id: str) -> str:
        return self._session_summaries.get(session_id, "")

    def save_summary(self, session_id: str, summary: str) -> None:
        self._session_summaries[session_id] = summary

    def get_user_profile(self, user_id: str) -> dict[str, Any]:
        return dict(self._user_profiles.get(user_id, {}))

    def update_user_profile(self, user_id: str, profile: dict[str, Any]) -> None:
        current = self._user_profiles.setdefault(user_id, {})
        current.update(profile or {})

    def estimate_tokens(self, text: str) -> int:
        return max(1, len(text or "") // 4)


runtime_store = RuntimeStore()
