from inspect import isawaitable
from time import perf_counter

from langchain_core.runnables import RunnableConfig

from app.config import get_settings
from app.core.logging import get_logger
from app.graph.state import TravelState
from app.models import TripPlan
from app.services.routing import GeoapifyRoutingProvider, RoutingProvider
from app.services.routing_enrichment import (
    enrich_trip_routes,
    has_routing_eligible_legs,
)

logger = get_logger(__name__)


async def routing_enrichment_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, TripPlan | None]:
    """Add optional Geoapify travel estimates without blocking the itinerary."""

    del config
    started_at = perf_counter()
    itinerary = state.get("itinerary")
    if itinerary is None:
        return {"itinerary": None}
    if not has_routing_eligible_legs(itinerary):
        return {"itinerary": itinerary}

    api_key = get_settings().GEOAPIFY_API_KEY
    if not api_key or not api_key.strip():
        logger.warning("routing_enrichment_skipped reason=missing_api_key")
        return {"itinerary": itinerary}

    provider: RoutingProvider | None = None
    try:
        provider = build_routing_provider(api_key)
        enriched = await enrich_trip_routes(itinerary, provider)
    except Exception as exc:
        logger.warning(
            "routing_provider_unavailable scope=trip error_type=%s",
            type(exc).__name__,
        )
        enriched = itinerary
    finally:
        if provider is not None:
            try:
                await _close_provider(provider)
            except Exception as exc:
                logger.warning(
                    "routing_provider_unavailable scope=close error_type=%s",
                    type(exc).__name__,
                )

    logger.info(
        "routing_enrichment_node exited duration=%.4fs",
        perf_counter() - started_at,
    )
    return {"itinerary": enriched}


def build_routing_provider(api_key: str) -> RoutingProvider:
    """Construct the private server-side Geoapify routing provider."""

    return GeoapifyRoutingProvider(api_key)


async def _close_provider(provider: RoutingProvider) -> None:
    close = getattr(provider, "aclose", None)
    if close is None:
        return
    result = close()
    if isawaitable(result):
        await result
