import json
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from app.schemas.chat_schema import ChatRequest, ChatResponse
from app.services.chat_service import ChatService, get_chat_service
from app.services.auth_service import Principal, require_principal
from app.services.persist_service import SessionOwnershipError

router = APIRouter()

@router.post("/v1/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    principal: Principal = Depends(require_principal),
    chat_service: ChatService = Depends(get_chat_service),
):
    authenticated_request = request.model_copy(update={"user_id": principal.user_id})
    try:
        return await chat_service.chat(authenticated_request)
    except SessionOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

@router.post("/v1/chat/stream")
async def chat_stream(
    request: ChatRequest,
    principal: Principal = Depends(require_principal),
    chat_service: ChatService = Depends(get_chat_service),
):
    authenticated_request = request.model_copy(update={"user_id": principal.user_id})
    try:
        await chat_service.ensure_session_access(authenticated_request)
    except SessionOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    async def event_generator():
        async for event in chat_service.chat_stream(authenticated_request, access_checked=True):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
