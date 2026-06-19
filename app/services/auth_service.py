from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings


_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user_id: str


def _validate_auth_config() -> None:
    if not settings.JWT_SECRET or settings.JWT_SECRET == "change-me" or len(settings.JWT_SECRET) < 32:
        raise RuntimeError("JWT_SECRET must be changed and contain at least 32 characters")
    if settings.JWT_ALGORITHM != "HS256":
        raise RuntimeError("Only HS256 is supported by this deployment")


def create_access_token(user_id: str, expires_minutes: int | None = None) -> str:
    _validate_auth_config()
    subject = str(user_id).strip()
    if not subject:
        raise ValueError("user_id must not be empty")
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=expires_minutes or settings.JWT_ACCESS_TOKEN_MINUTES)
    return jwt.encode(
        {
            "sub": subject,
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
            "iat": now,
            "nbf": now,
            "exp": expires,
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> Principal:
    _validate_auth_config()
    payload = jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
        issuer=settings.JWT_ISSUER,
        audience=settings.JWT_AUDIENCE,
        options={"require": ["sub", "iss", "aud", "iat", "nbf", "exp"]},
    )
    user_id = str(payload.get("sub") or "").strip()
    if not user_id:
        raise jwt.InvalidTokenError("Missing token subject")
    return Principal(user_id=user_id)


async def require_principal(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> Principal:
    if not settings.AUTH_REQUIRED:
        raise HTTPException(status_code=503, detail="Authenticated API access is disabled")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer access token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return decode_access_token(credentials.credentials)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
