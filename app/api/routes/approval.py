from fastapi import APIRouter

from app.schemas.approval import ApprovalRequest, ApprovalResponse
from app.services.graph_services import GraphService

router = APIRouter()
service = GraphService()


@router.post("/chat/approve", response_model=ApprovalResponse)
async def approve(request: ApprovalRequest) -> ApprovalResponse:
    """Resume an interrupted chat workflow with a human approval decision."""

    return await service.aresume(request)
