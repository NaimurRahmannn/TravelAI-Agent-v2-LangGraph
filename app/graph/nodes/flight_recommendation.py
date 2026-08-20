from inspect import isawaitable
from time import perf_counter

from langchain_core.runnables import RunnableConfig

from app.config import get_settings
from app.core.logging import get_logger
from app.graph.state import TravelState
from app.models import TripPlan
from app.services.flight_recommendation import (
    enrich_flight_recommendations,
    mark_flight_recommendations_unavailable,
)
from app.services.recommendations.base import FlightProvider
from app.services.recommendations.flights import (
    GeoapifyAirportResolver,
    SwoopFlightProvider,
)

logger = get_logger(__name__)


async def flight_recommendation_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, TripPlan | None]:
    """Add optional ranked flight results without blocking the itinerary."""

    del config
    started_at = perf_counter()
    itinerary = state.get("itinerary")
    if itinerary is None:
        return {"itinerary": None}

    geoapify_api_key = get_settings().GEOAPIFY_API_KEY
    if not geoapify_api_key or not geoapify_api_key.strip():
        logger.warning("flight_recommendation_skipped reason=missing_geoapify_key")
        return {"itinerary": mark_flight_recommendations_unavailable(itinerary)}

    provider: FlightProvider | None = None
    try:
        provider = build_flight_provider(geoapify_api_key)
        enriched = await enrich_flight_recommendations(itinerary, provider)
    except Exception as exc:
        logger.warning(
            "flight_recommendation_unavailable error_type=%s",
            type(exc).__name__,
        )
        enriched = mark_flight_recommendations_unavailable(itinerary)
    finally:
        if provider is not None:
            try:
                await _close_provider(provider)
            except Exception as exc:
                logger.warning(
                    "flight_provider_close_failed error_type=%s",
                    type(exc).__name__,
                )

    logger.info(
        "flight_recommendation_node exited duration=%.4fs",
        perf_counter() - started_at,
    )
    return {"itinerary": enriched}


def build_flight_provider(geoapify_api_key: str) -> FlightProvider:
    """Construct Swoop with Geoapify-backed airport resolution."""

    return SwoopFlightProvider(GeoapifyAirportResolver(geoapify_api_key))


async def _close_provider(provider: FlightProvider) -> None:
    close = getattr(provider, "aclose", None)
    if close is None:
        return
    result = close()
    if isawaitable(result):
        await result
