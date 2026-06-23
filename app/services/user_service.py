from __future__ import annotations

import uuid
from dataclasses import dataclass

import bcrypt

from app.db.postgres import get_pool


@dataclass(frozen=True)
class User:
    id: str
    username: str


class UserAlreadyExistsError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


def _hash_password(password: str) -> str:
    # bcrypt giới hạn 72 byte; cắt để tránh lỗi/silent-truncation.
    raw = password.encode("utf-8")[:72]
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


class UserService:
    async def register(self, username: str, password: str) -> User:
        username = username.strip()
        if not username or not password:
            raise InvalidCredentialsError("Tên đăng nhập và mật khẩu không được để trống")

        user_id = uuid.uuid4()
        password_hash = _hash_password(password)
        pool = await get_pool()
        async with pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT 1 FROM users WHERE username = $1", username
            )
            if exists:
                raise UserAlreadyExistsError("Tên đăng nhập đã tồn tại")
            await conn.execute(
                """
                INSERT INTO users (id, username, password_hash, name)
                VALUES ($1, $2, $3, $4)
                """,
                user_id,
                username,
                password_hash,
                username,
            )
        return User(id=str(user_id), username=username)

    async def authenticate(self, username: str, password: str) -> User:
        username = username.strip()
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, username, password_hash FROM users WHERE username = $1",
                username,
            )
        if row is None or not row["password_hash"]:
            raise InvalidCredentialsError("Sai tên đăng nhập hoặc mật khẩu")
        if not _verify_password(password, row["password_hash"]):
            raise InvalidCredentialsError("Sai tên đăng nhập hoặc mật khẩu")
        return User(id=str(row["id"]), username=row["username"])


user_service = UserService()
