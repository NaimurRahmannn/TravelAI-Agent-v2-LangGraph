from datetime import UTC, datetime
from time import perf_counter
from typing import cast

from langchain_core.runnables import RunnableConfig

from app.config import get_settings
from app.core.logging import get_logger
from app.graph.state import TravelState
from app.models import (
    FlightSearchCache,
    FlightSearchRequest,
    FlightSearchScope,
    TripPlan,
)
from app.services.flight_recommendation import (
    build_flight_provider,
    build_flight_search_cache,
    build_flight_search_request,
    can_reuse_flight_cache,
    close_flight_provider,
    flight_requests_match,
    is_flight_cache_fresh,
    mark_flight_recommendations_unavailable,
    search_flight_recommendations,
    update_flight_recommendations,
)
from app.services.recommendations.base import FlightProvider
from app.services.recommendations.ranking import build_recommendation_status

logger = get_logger(__name__)


async def flight_recommendation_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, TripPlan | FlightSearchCache | None]:
    """Add optional ranked flight results without blocking the itinerary."""

    del config
    started_at = perf_counter()
    itinerary = state.get("itinerary")
    if itinerary is None:
        return {"itinerary": None}

    scope = _validated_scope(state.get("flight_search_scope"))
    current_request = build_flight_search_request(itinerary, scope=scope)
    if current_request is None:
        return {
            "itinerary": update_flight_recommendations(
                itinerary,
                flights=[],
                status=build_recommendation_status(searched=False),
            )
        }

    cache = _validated_cache(state.get("flight_search_cache"))
    now = datetime.now(UTC)
    if can_reuse_flight_cache(cache, current_request, now):
        assert cache is not None
        age_seconds = max(0, int((now - cache.searched_at).total_seconds()))
        logger.info(
            "flight_cache_hit age_seconds=%s status=%s result_count=%s",
            age_seconds,
            cache.status.status,
            len(cache.flights),
        )
        enriched = update_flight_recommendations(
            itinerary,
            flights=cache.flights,
            status=cache.status,
        )
        logger.info(
            "flight_recommendation_node exited source=cache duration=%.4fs",
            perf_counter() - started_at,
        )
        return {"itinerary": enriched, "flight_search_cache": cache}

    _log_cache_miss(cache, current_request, now)

    geoapify_api_key = get_settings().GEOAPIFY_API_KEY
    if not geoapify_api_key or not geoapify_api_key.strip():
        logger.warning("flight_recommendation_skipped reason=missing_geoapify_key")
        return {
            "itinerary": mark_flight_recommendations_unavailable(
                itinerary,
                scope=scope,
            )
        }

    provider: FlightProvider | None = None
    stored_cache: FlightSearchCache | None = None
    try:
        provider = build_flight_provider(geoapify_api_key)
        enriched = await search_flight_recommendations(
            itinerary,
            current_request,
            provider,
        )
        stored_cache = build_flight_search_cache(current_request, enriched)
        logger.info(
            "flight_cache_store status=%s result_count=%s",
            stored_cache.status.status,
            len(stored_cache.flights),
        )
    except Exception as exc:
        logger.warning(
            "flight_recommendation_unavailable error_type=%s",
            type(exc).__name__,
        )
        enriched = mark_flight_recommendations_unavailable(itinerary, scope=scope)
    finally:
        if provider is not None:
            try:
                await close_flight_provider(provider)
            except Exception as exc:
                logger.warning(
                    "flight_provider_close_failed error_type=%s",
                    type(exc).__name__,
                )

    logger.info(
        "flight_recommendation_node exited duration=%.4fs",
        perf_counter() - started_at,
    )
    result: dict[str, TripPlan | FlightSearchCache | None] = {"itinerary": enriched}
    if stored_cache is not None:
        result["flight_search_cache"] = stored_cache
    return result


def _validated_scope(value: object) -> FlightSearchScope:
    if value in {"outbound", "return", "round_trip"}:
        return cast(FlightSearchScope, value)
    return "round_trip"


def _validated_cache(value: object) -> FlightSearchCache | None:
    if value is None:
        return None
    try:
        return FlightSearchCache.model_validate(value)
    except ValueError:
        logger.warning("flight_cache_miss reason=invalid_checkpoint_value")
        return None


def _log_cache_miss(
    cache: FlightSearchCache | None,
    request: FlightSearchRequest,
    now: datetime,
) -> None:
    if cache is None:
        logger.info("flight_cache_miss reason=empty")
        return
    if cache.status.status not in {"available", "no_results"}:
        logger.info("flight_cache_miss reason=status status=%s", cache.status.status)
        return
    if not flight_requests_match(cache.request, request):
        logger.info("flight_cache_request_changed")
        return
    if not is_flight_cache_fresh(cache, now):
        age_seconds = int((now - cache.searched_at).total_seconds())
        logger.info("flight_cache_expired age_seconds=%s", age_seconds)
        return
    logger.info("flight_cache_miss reason=unknown")
