from time import perf_counter
from typing import Any

from app.config import get_settings
from app.core.logging import get_logger
from app.graph.builder import get_graph
from app.models import TripPlan
from app.schemas.api import FlightRefreshRequest, FlightRefreshResponse
from app.services.flight_recommendation import (
    build_flight_provider,
    build_flight_search_cache,
    build_flight_search_request,
    close_flight_provider,
    search_flight_options,
    search_flight_recommendations,
    update_split_flight_recommendations,
)
from app.services.recommendations.base import FlightProvider

logger = get_logger(__name__)
_REFRESH_FAILURE_DETAIL = (
    "We couldn't refresh flight prices right now. Your previous flight "
    "recommendations are still available."
)


class FlightRefreshError(ValueError):
    """A traveler-safe explicit refresh error that leaves state unchanged."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class FlightRefreshService:
    """Force one flight-only provider search against checkpointed trip state."""

    @staticmethod
    async def _get_graph() -> Any:
        return await get_graph()

    @staticmethod
    def _build_provider(api_key: str) -> FlightProvider:
        return build_flight_provider(api_key)

    async def refresh(
        self,
        request: FlightRefreshRequest,
    ) -> FlightRefreshResponse:
        started_at = perf_counter()
        graph = await self._get_graph()
        config = {"configurable": {"thread_id": request.thread_id}}
        snapshot = await graph.aget_state(config)
        values = snapshot.values if snapshot is not None else None
        if snapshot is None or snapshot.created_at is None or not values:
            raise FlightRefreshError(404, "Travel thread was not found.")

        try:
            itinerary = TripPlan.model_validate(values.get("itinerary"))
        except ValueError as exc:
            raise FlightRefreshError(
                409,
                "The travel thread does not have a usable itinerary.",
            ) from exc

        has_split_candidates = bool(
            itinerary.recommendations
            and (
                itinerary.recommendations.outbound_flights
                or itinerary.recommendations.return_flights
                or itinerary.recommendations.outbound_flight_status.status
                != "not_searched"
                or itinerary.recommendations.return_flight_status.status
                != "not_searched"
            )
        )
        current_request = build_flight_search_request(itinerary)
        if current_request is None:
            raise FlightRefreshError(
                409,
                "The current itinerary does not have enough information to "
                "refresh flights.",
            )

        api_key = get_settings().GEOAPIFY_API_KEY
        if not api_key or not api_key.strip():
            raise FlightRefreshError(503, _REFRESH_FAILURE_DETAIL)

        logger.info("flight_refresh_forced thread_id=%s", request.thread_id)
        provider: FlightProvider | None = None
        try:
            provider = self._build_provider(api_key)
            if has_split_candidates:
                outbound_request = build_flight_search_request(
                    itinerary,
                    scope="outbound",
                )
                return_request = build_flight_search_request(
                    itinerary,
                    scope="return",
                )
                if outbound_request is None or return_request is None:
                    raise ValueError("Split flight search inputs are incomplete")
                outbound, outbound_status = await search_flight_options(
                    outbound_request,
                    provider,
                )
                return_flights, return_status = await search_flight_options(
                    return_request,
                    provider,
                )
                enriched = update_split_flight_recommendations(
                    itinerary,
                    outbound=outbound,
                    outbound_status=outbound_status,
                    return_flights=return_flights,
                    return_status=return_status,
                )
                cache = None
            else:
                enriched = await search_flight_recommendations(
                    itinerary,
                    current_request,
                    provider,
                )
                cache = build_flight_search_cache(current_request, enriched)
                logger.info(
                    "flight_cache_store source=explicit_refresh status=%s "
                    "result_count=%s",
                    cache.status.status,
                    len(cache.flights),
                )
        except Exception as exc:
            logger.warning(
                "flight_refresh_failed_preserving_cache thread_id=%s "
                "error_type=%s",
                request.thread_id,
                type(exc).__name__,
            )
            raise FlightRefreshError(503, _REFRESH_FAILURE_DETAIL) from exc
        finally:
            if provider is not None:
                try:
                    await close_flight_provider(provider)
                except Exception as exc:
                    logger.warning(
                        "flight_provider_close_failed error_type=%s",
                        type(exc).__name__,
                    )

        await graph.aupdate_state(
            config,
            {
                "itinerary": enriched,
                "flight_search_cache": cache,
            },
            as_node="memory_write",
        )
        logger.info(
            "flight_refresh_completed thread_id=%s status=%s result_count=%s "
            "duration=%.4fs",
            request.thread_id,
            enriched.recommendations.flight_status.status,
            len(enriched.recommendations.flights),
            perf_counter() - started_at,
        )
        return FlightRefreshResponse(
            thread_id=request.thread_id,
            message="Flight recommendations refreshed.",
            itinerary=enriched,
            travel_selections=values.get("travel_selections"),
            trip_cost_summary=values.get("trip_cost_summary"),
            detailed_routing_plan=values.get("detailed_routing_plan"),
            confirmed_snapshot=values.get("confirmed_snapshot"),
        )
