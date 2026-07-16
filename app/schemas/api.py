from typing import Literal, Optional

from pydantic import BaseModel

StreamMode = Literal["updates", "messages", "debug"]


class ChatRequest(BaseModel):
    """Request body for a chat invocation."""

    message: str
    thread_id: Optional[str] = None
    user_id: Optional[str] = None
    stream_mode: StreamMode = "messages"


class ChatResponse(BaseModel):
    """Response body returned by the travel graph."""

    response: str
    thread_id: str
