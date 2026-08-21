from fastapi import APIRouter, HTTPException

from app.schemas.api import TravelSelectionRequest, TravelSelectionResponse
from app.services.travel_selection import (
    TravelSelectionError,
    TravelSelectionService,
)

router = APIRouter()
service = TravelSelectionService()


@router.post("/trip/select-travel", response_model=TravelSelectionResponse)
async def select_travel(
    request: TravelSelectionRequest,
) -> TravelSelectionResponse:
    """Confirm one flight and one hotel per stay from stored recommendations."""

    try:
        return await service.confirm(request)
    except TravelSelectionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
