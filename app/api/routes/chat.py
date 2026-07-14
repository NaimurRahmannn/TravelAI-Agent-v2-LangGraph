from fastapi import APIRouter

from app.schemas.api import ChatRequest, ChatResponse
from app.services.graph_services import GraphService

router = APIRouter()
service = GraphService()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Handle a chat request through the graph service."""

    return await service.ainvoke(request)
