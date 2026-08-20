from inspect import isawaitable
from time import perf_counter

from langchain_core.runnables import RunnableConfig

from app.config import get_settings
from app.core.logging import get_logger
from app.graph.state import TravelState
from app.models import TripPlan
from app.services.hotel_recommendation import (
    enrich_hotel_recommendations,
    mark_hotel_recommendations_unavailable,
)
from app.services.places import GeoapifyPlacesProvider, PlacesProvider
from app.services.recommendations.base import HotelProvider
from app.services.recommendations.hotels import LiteApiHotelProvider

logger = get_logger(__name__)


async def hotel_recommendation_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, TripPlan | None]:
    """Add optional LiteAPI hotel rates without blocking the itinerary."""

    del config
    started_at = perf_counter()
    itinerary = state.get("itinerary")
    if itinerary is None:
        return {"itinerary": None}

    settings = get_settings()
    api_key = settings.LITEAPI_API_KEY
    if not api_key or not api_key.strip():
        logger.warning("hotel_recommendation_skipped reason=missing_liteapi_key")
        return {"itinerary": mark_hotel_recommendations_unavailable(itinerary)}

    hotel_provider: HotelProvider | None = None
    anchor_provider: PlacesProvider | None = None
    try:
        hotel_provider = LiteApiHotelProvider(api_key)
        if settings.GEOAPIFY_API_KEY and settings.GEOAPIFY_API_KEY.strip():
            anchor_provider = GeoapifyPlacesProvider(settings.GEOAPIFY_API_KEY)
        itinerary = await _infer_guest_nationality(itinerary, anchor_provider)
        enriched = await enrich_hotel_recommendations(
            itinerary,
            hotel_provider,
            anchor_provider=anchor_provider,
        )
    except Exception as exc:
        logger.warning(
            "hotel_recommendation_unavailable error_type=%s",
            type(exc).__name__,
        )
        enriched = mark_hotel_recommendations_unavailable(itinerary)
    finally:
        for provider in (hotel_provider, anchor_provider):
            if provider is None:
                continue
            try:
                await _close_provider(provider)
            except Exception as exc:
                logger.warning(
                    "hotel_provider_close_failed error_type=%s",
                    type(exc).__name__,
                )

    logger.info(
        "hotel_recommendation_node exited duration=%.4fs",
        perf_counter() - started_at,
    )
    return {"itinerary": enriched}


async def _infer_guest_nationality(
    itinerary: TripPlan,
    provider: PlacesProvider | None,
) -> TripPlan:
    """Infer LiteAPI nationality from the traveler's origin when available."""

    if itinerary.guest_nationality_country_code or provider is None:
        return itinerary
    if not itinerary.origin or not itinerary.origin.strip():
        return itinerary

    try:
        resolution = await provider.resolve_place(
            name=itinerary.origin,
            location_hint=None,
            city=None,
            destination=itinerary.origin,
        )
    except Exception as exc:
        logger.warning(
            "guest_nationality_inference_failed error_type=%s",
            type(exc).__name__,
        )
        return itinerary

    country_code = resolution.place.country_code if resolution.place else None
    if not country_code or len(country_code) != 2 or not country_code.isalpha():
        logger.info("guest_nationality_inference_unavailable origin=%s", itinerary.origin)
        return itinerary

    normalized = country_code.upper()
    logger.info(
        "guest_nationality_inferred origin=%s country_code=%s",
        itinerary.origin,
        normalized,
    )
    return itinerary.model_copy(
        update={"guest_nationality_country_code": normalized}
    )


async def _close_provider(provider: object) -> None:
    close = getattr(provider, "aclose", None)
    if close is None:
        return
    result = close()
    if isawaitable(result):
        await result
