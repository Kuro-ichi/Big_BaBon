import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from app.schemas.chat_schema import ChatRequest, ChatResponse
from app.services.chat_service import ChatService, get_chat_service

router = APIRouter()

@router.post("/v1/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    chat_service: ChatService = Depends(get_chat_service),
):
    return await chat_service.chat(request)

@router.post("/v1/chat/stream")
async def chat_stream(
    request: ChatRequest,
    chat_service: ChatService = Depends(get_chat_service),
):
    async def event_generator():
        result = await chat_service.chat_stream(request)

        answer = result.get("answer", "")

        for i in range(0, len(answer), 10):
            chunk = answer[i:i+10]

            data = {
                "type": "token",
                "content": chunk,
                "request_id": result["request_id"]
            }

            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

        done_data = {
            "type": "done",
            "request_id": result["request_id"],
            "route": result.get("route"),
            "confidence": result.get("confidence"),
            "citations": result.get("citations", []),
            "metrics": result.get("metrics", {}),
        }
        yield f"data: {json.dumps(done_data, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
