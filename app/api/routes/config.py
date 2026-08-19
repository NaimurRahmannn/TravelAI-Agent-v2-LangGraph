from fastapi import APIRouter, Depends, Response

from app.config import Settings, get_settings
from app.schemas.api import MapsConfigResponse

router = APIRouter(prefix="/config", tags=["config"])


@router.get("/maps", response_model=MapsConfigResponse)
async def maps_config(
    response: Response,
    settings: Settings = Depends(get_settings),
) -> MapsConfigResponse:
    """Return only the browser-restricted key used for Geoapify map tiles."""

    response.headers["Cache-Control"] = "no-store"
    api_key = _non_empty(settings.GEOAPIFY_MAPS_API_KEY)
    if api_key is None:
        return MapsConfigResponse(enabled=False)
    return MapsConfigResponse(
        enabled=True,
        api_key=api_key,
    )


def _non_empty(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None
