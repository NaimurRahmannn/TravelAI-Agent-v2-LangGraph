from inspect import isawaitable
from datetime import date
from time import perf_counter

from langchain_core.runnables import RunnableConfig

from app.config import get_settings
from app.core.logging import get_logger
from app.graph.state import TravelState
from app.models import RecommendationDomainState, TripPlan
from app.services.hotel_recommendation import (
    enrich_hotel_recommendations,
    mark_hotel_recommendations_unavailable,
    update_hotel_recommendations,
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
        if state.get("turn_intent") == "extend_trip":
            return {
                "itinerary": _mark_extension_hotels_unavailable(itinerary)
            }
        return {"itinerary": mark_hotel_recommendations_unavailable(itinerary)}

    hotel_provider: HotelProvider | None = None
    anchor_provider: PlacesProvider | None = None
    try:
        hotel_provider = LiteApiHotelProvider(api_key)
        if settings.GEOAPIFY_API_KEY and settings.GEOAPIFY_API_KEY.strip():
            anchor_provider = GeoapifyPlacesProvider(settings.GEOAPIFY_API_KEY)
        itinerary = await _infer_guest_nationality(itinerary, anchor_provider)
        if (
            state.get("turn_intent") == "extend_trip"
            and state.get("extension_original_end_date") is not None
        ):
            enriched = await _enrich_extension_hotels(
                itinerary,
                state["extension_original_end_date"],
                hotel_provider,
                anchor_provider=anchor_provider,
            )
        else:
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
    """Derive hotel-search nationality exclusively from the trip origin."""

    origin_based = itinerary.model_copy(
        update={"guest_nationality_country_code": None}
    )
    if provider is None or not itinerary.origin or not itinerary.origin.strip():
        return origin_based

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
        return origin_based

    country_code = resolution.place.country_code if resolution.place else None
    if not country_code or len(country_code) != 2 or not country_code.isalpha():
        logger.info("guest_nationality_inference_unavailable origin=%s", itinerary.origin)
        return origin_based

    normalized = country_code.upper()
    logger.info(
        "guest_nationality_inferred origin=%s country_code=%s",
        itinerary.origin,
        normalized,
    )
    return origin_based.model_copy(
        update={"guest_nationality_country_code": normalized}
    )


async def _enrich_extension_hotels(
    itinerary: TripPlan,
    old_end: date,
    provider: HotelProvider,
    *,
    anchor_provider: PlacesProvider | None,
) -> TripPlan:
    """Search only the added nights and merge them with prior hotel options."""

    extension_days = [
        day for day in itinerary.days if day.date is not None and day.date >= old_end
    ]
    if not extension_days:
        return itinerary
    scoped = itinerary.model_copy(
        update={"days": extension_days, "recommendations": None}
    )
    scoped_result = await enrich_hotel_recommendations(
        scoped,
        provider,
        anchor_provider=anchor_provider,
    )
    current = itinerary.recommendations
    prior_hotels = (
        [hotel for hotel in current.hotels if hotel.check_out <= old_end]
        if current is not None
        else []
    )
    scoped_recommendations = scoped_result.recommendations
    added_hotels = (
        scoped_recommendations.hotels if scoped_recommendations is not None else []
    )
    status = (
        scoped_recommendations.hotel_status
        if scoped_recommendations is not None
        else itinerary.recommendations.hotel_status
        if itinerary.recommendations is not None
        else None
    )
    if status is None:
        return itinerary
    return update_hotel_recommendations(
        itinerary,
        hotels=[*prior_hotels, *added_hotels],
        status=status,
    )


def _mark_extension_hotels_unavailable(itinerary: TripPlan) -> TripPlan:
    recommendations = itinerary.recommendations
    if recommendations is None:
        return mark_hotel_recommendations_unavailable(itinerary)
    return update_hotel_recommendations(
        itinerary,
        hotels=list(recommendations.hotels),
        status=RecommendationDomainState(status="unavailable"),
    )


async def _close_provider(provider: object) -> None:
    close = getattr(provider, "aclose", None)
    if close is None:
        return
    result = close()
    if isawaitable(result):
        await result
