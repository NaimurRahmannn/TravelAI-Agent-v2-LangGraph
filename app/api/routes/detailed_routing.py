from fastapi import APIRouter, HTTPException

from app.schemas.api import DetailedRoutingRequest, DetailedRoutingResponse
from app.services.detailed_routing import (
    DetailedRoutingError,
    DetailedRoutingService,
)

router = APIRouter()
service = DetailedRoutingService()


@router.post("/trip/detailed-routing", response_model=DetailedRoutingResponse)
async def create_detailed_routing_plan(
    request: DetailedRoutingRequest,
) -> DetailedRoutingResponse:
    """Build a timetable from authoritative checkpointed travel selections."""

    try:
        return await service.generate(request)
    except DetailedRoutingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
