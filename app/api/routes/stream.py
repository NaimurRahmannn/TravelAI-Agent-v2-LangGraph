from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.schemas.api import ChatRequest
from app.services.stream_service import StreamService

router = APIRouter()
service = StreamService()


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Stream a chat request as server-sent events."""

    return StreamingResponse(
        service.chat_stream(request),
        media_type="text/event-stream",
    )
