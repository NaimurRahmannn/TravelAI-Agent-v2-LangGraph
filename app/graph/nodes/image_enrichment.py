from inspect import isawaitable
from time import perf_counter

from langchain_core.runnables import RunnableConfig

from app.config import get_settings
from app.core.logging import get_logger
from app.graph.state import TravelState
from app.models import TripPlan
from app.services.image_enrichment import (
    enrich_trip_images,
    has_image_eligible_activities,
)
from app.services.images import PexelsImageProvider, PlaceImageProvider

logger = get_logger(__name__)


async def image_enrichment_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, TripPlan | None]:
    """Add optional Pexels image data while preserving the itinerary."""

    del config
    started_at = perf_counter()
    itinerary = state.get("itinerary")
    if itinerary is None:
        return {"itinerary": None}
    if not has_image_eligible_activities(itinerary):
        return {"itinerary": itinerary}

    api_key = get_settings().PEXELS_API_KEY
    if not api_key or not api_key.strip():
        logger.warning("image_resolution_skipped reason=missing_pexels_api_key")
        return {"itinerary": itinerary}

    provider: PlaceImageProvider | None = None
    try:
        provider = build_image_provider(api_key)
        enriched = await enrich_trip_images(itinerary, provider)
    except Exception as exc:
        logger.warning(
            "image_provider_unavailable scope=trip error_type=%s",
            type(exc).__name__,
        )
        enriched = itinerary
    finally:
        if provider is not None:
            try:
                await _close_provider(provider)
            except Exception as exc:
                logger.warning(
                    "image_provider_unavailable scope=close error_type=%s",
                    type(exc).__name__,
                )

    logger.info(
        "image_enrichment_node exited duration=%.4fs",
        perf_counter() - started_at,
    )
    return {"itinerary": enriched}


def build_image_provider(api_key: str) -> PlaceImageProvider:
    """Construct the configured image provider behind the protocol boundary."""

    return PexelsImageProvider(api_key)


async def _close_provider(provider: PlaceImageProvider) -> None:
    close = getattr(provider, "aclose", None)
    if close is None:
        return
    result = close()
    if isawaitable(result):
        await result
