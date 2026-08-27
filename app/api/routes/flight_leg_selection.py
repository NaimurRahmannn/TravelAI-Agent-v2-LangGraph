from fastapi import APIRouter, HTTPException

from app.schemas.api import FlightLegSelectionRequest, FlightLegSelectionResponse
from app.services.flight_leg_selection import FlightLegSelectionService
from app.services.travel_selection import TravelSelectionError

router = APIRouter()
service = FlightLegSelectionService()


@router.post("/trip/select-flight-leg", response_model=FlightLegSelectionResponse)
async def select_flight_leg(
    request: FlightLegSelectionRequest,
) -> FlightLegSelectionResponse:
    try:
        return await service.confirm(request)
    except TravelSelectionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
