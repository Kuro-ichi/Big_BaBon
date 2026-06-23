from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.core.config import settings
from app.services.auth_service import create_access_token
from app.services.user_service import (
    InvalidCredentialsError,
    UserAlreadyExistsError,
    user_service,
)

router = APIRouter()


class CredentialsRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: str
    expires_in_minutes: int


def _token_response(user_id: str, username: str) -> TokenResponse:
    # Token sub = user uuid để khớp FK users.id khi persist chat.
    token = create_access_token(user_id)
    return TokenResponse(
        access_token=token,
        user_id=user_id,
        username=username,
        expires_in_minutes=settings.JWT_ACCESS_TOKEN_MINUTES,
    )


@router.post("/v1/auth/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: CredentialsRequest) -> TokenResponse:
    try:
        user = await user_service.register(payload.username, payload.password)
    except UserAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _token_response(user.id, user.username)


@router.post("/v1/auth/login", response_model=TokenResponse)
async def login(payload: CredentialsRequest) -> TokenResponse:
    try:
        user = await user_service.authenticate(payload.username, payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return _token_response(user.id, user.username)
