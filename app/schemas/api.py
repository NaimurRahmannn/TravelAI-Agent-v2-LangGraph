from typing import Optional

from pydantic import BaseModel


class ChatRequest(BaseModel):
    """Request body for a chat invocation."""

    message: str
    thread_id: Optional[str] = None


class ChatResponse(BaseModel):
    """Response body returned by the travel graph."""

    response: str
    thread_id: str
