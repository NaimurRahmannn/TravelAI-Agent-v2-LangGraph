from inspect import isawaitable
from time import perf_counter

from langchain_core.runnables import RunnableConfig

from app.config import get_settings
from app.core.logging import get_logger
from app.graph.state import TravelState
from app.models import TripPlan
from app.services.place_enrichment import enrich_trip_places
from app.services.places import GeoapifyPlacesProvider, PlacesProvider

logger = get_logger(__name__)


async def place_enrichment_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, TripPlan | None]:
    """Enrich a generated itinerary while preserving it on provider failures."""

    del config
    started_at = perf_counter()
    itinerary = state.get("itinerary")
    if itinerary is None:
        return {"itinerary": None}

    api_key = get_settings().GEOAPIFY_API_KEY
    if not api_key or not api_key.strip():
        logger.warning("place_resolution_skipped reason=missing_api_key")
        return {"itinerary": itinerary}

    provider: PlacesProvider | None = None
    try:
        provider = build_places_provider(api_key)
        enriched = await enrich_trip_places(itinerary, provider)
    except Exception as exc:
        logger.warning(
            "place_resolution_provider_error scope=trip error_type=%s",
            type(exc).__name__,
        )
        enriched = itinerary
    finally:
        if provider is not None:
            try:
                await _close_provider(provider)
            except Exception as exc:
                logger.warning(
                    "place_resolution_provider_error scope=close error_type=%s",
                    type(exc).__name__,
                )

    logger.info(
        "place_enrichment_node exited duration=%.4fs",
        perf_counter() - started_at,
    )
    return {"itinerary": enriched}


def build_places_provider(api_key: str) -> PlacesProvider:
    """Construct the configured place provider behind the protocol boundary."""

    return GeoapifyPlacesProvider(api_key)


async def _close_provider(provider: PlacesProvider) -> None:
    close = getattr(provider, "aclose", None)
    if close is None:
        return
    result = close()
    if isawaitable(result):
        await result
