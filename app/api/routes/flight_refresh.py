from fastapi import APIRouter, HTTPException

from app.schemas.api import FlightRefreshRequest, FlightRefreshResponse
from app.services.flight_refresh import FlightRefreshError, FlightRefreshService

router = APIRouter()
service = FlightRefreshService()


@router.post("/trip/refresh-flights", response_model=FlightRefreshResponse)
async def refresh_flights(
    request: FlightRefreshRequest,
) -> FlightRefreshResponse:
    """Force a flight-only refresh using authoritative checkpoint state."""

    try:
        return await service.refresh(request)
    except FlightRefreshError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
