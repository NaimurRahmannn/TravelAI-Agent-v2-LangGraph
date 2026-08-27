import asyncio
from inspect import isawaitable
from time import perf_counter
from typing import Any

from app.config import get_settings
from app.core.logging import get_logger
from app.graph.builder import get_graph
from app.models import (
    ConfirmedTripSnapshot,
    DetailedRoutingPlan,
    TravelSelections,
    TripCostSummary,
    TripPlan,
)
from app.schemas.api import DetailedRoutingRequest, DetailedRoutingResponse
from app.services.detailed_routing_context import (
    DetailedRoutingContext,
    DetailedRoutingContextError,
    RoutingPoint,
    build_detailed_routing_context,
    collect_required_route_legs,
    with_resolved_point,
)
from app.services.detailed_routing_estimates import (
    DetailedPlanningEstimator,
    GeminiDetailedPlanningEstimator,
    build_planning_estimates,
)
from app.services.detailed_timetable import build_detailed_timetable
from app.services.places import GeoapifyPlacesProvider, PlacesProvider
from app.services.routing import GeoapifyRoutingProvider, RoutingProvider

logger = get_logger(__name__)
LOCATION_RESOLUTION_CONCURRENCY = 3


class DetailedRoutingError(ValueError):
    """A deterministic endpoint error with a traveler-safe explanation."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class DetailedRoutingService:
    """Generate and atomically persist one opt-in detailed routing plan."""

    @staticmethod
    async def _get_graph() -> Any:
        return await get_graph()

    @staticmethod
    def _build_places_provider(api_key: str) -> PlacesProvider:
        return GeoapifyPlacesProvider(api_key)

    @staticmethod
    def _build_routing_provider(api_key: str) -> RoutingProvider:
        return GeoapifyRoutingProvider(api_key)

    @staticmethod
    def _build_planning_estimator() -> DetailedPlanningEstimator:
        return GeminiDetailedPlanningEstimator()

    async def generate(
        self,
        request: DetailedRoutingRequest,
    ) -> DetailedRoutingResponse:
        started_at = perf_counter()
        graph = await self._get_graph()
        config = {"configurable": {"thread_id": request.thread_id}}
        snapshot = await graph.aget_state(config)
        values = snapshot.values if snapshot is not None else None
        if snapshot is None or snapshot.created_at is None or not values:
            raise DetailedRoutingError(404, "Travel thread was not found.")

        itinerary = _validated_state_model(values.get("itinerary"), TripPlan)
        selections = _validated_state_model(
            values.get("travel_selections"),
            TravelSelections,
        )
        cost_summary = _validated_state_model(
            values.get("trip_cost_summary"),
            TripCostSummary,
        )
        if itinerary is None or selections is None or cost_summary is None:
            raise DetailedRoutingError(
                409,
                "Select your flight and hotel options before creating the detailed "
                "routing plan.",
            )
        try:
            context = build_detailed_routing_context(itinerary, selections)
        except DetailedRoutingContextError as exc:
            raise DetailedRoutingError(409, str(exc)) from exc

        logger.info(
            "detailed_routing_generation_started thread_id=%s day_count=%s",
            request.thread_id,
            len(context.days),
        )
        settings = get_settings()
        places_provider: PlacesProvider | None = None
        routing_provider: RoutingProvider | None = None
        if settings.GEOAPIFY_API_KEY and settings.GEOAPIFY_API_KEY.strip():
            places_provider = self._build_places_provider(settings.GEOAPIFY_API_KEY)
            routing_provider = self._build_routing_provider(
                settings.GEOAPIFY_API_KEY
            )
        try:
            context = await resolve_missing_context_coordinates(
                context,
                places_provider,
            )
            required_legs = collect_required_route_legs(context)
            estimates = await build_planning_estimates(
                context,
                required_legs,
                routing_provider=routing_provider,
                planning_estimator=self._build_planning_estimator(),
            )
            detailed_plan = build_detailed_timetable(context, estimates)
        finally:
            await _close_provider(places_provider)
            await _close_provider(routing_provider)

        snapshot_update = None
        try:
            confirmed = ConfirmedTripSnapshot.model_validate(
                values.get("confirmed_snapshot")
            )
            snapshot_update = confirmed.model_copy(
                update={"routing_plan": detailed_plan}
            )
        except ValueError:
            pass
        update = {"detailed_routing_plan": detailed_plan}
        if snapshot_update is not None:
            update["confirmed_snapshot"] = snapshot_update
        await graph.aupdate_state(
            config,
            update,
            as_node="memory_write",
        )
        logger.info(
            "detailed_routing_generation_completed thread_id=%s day_count=%s "
            "route_leg_count=%s geoapify_success_count=%s "
            "geoapify_failure_count=%s llm_fallback_count=%s "
            "activity_estimate_count=%s warning_count=%s duration=%.4fs",
            request.thread_id,
            len(detailed_plan.days),
            len(required_legs),
            estimates.geoapify_success_count,
            estimates.geoapify_failure_count,
            estimates.llm_route_count,
            estimates.llm_activity_count,
            len(detailed_plan.warnings),
            perf_counter() - started_at,
        )
        return DetailedRoutingResponse(
            thread_id=request.thread_id,
            detailed_routing_plan=detailed_plan,
        )


async def resolve_missing_context_coordinates(
    context: DetailedRoutingContext,
    provider: PlacesProvider | None,
) -> DetailedRoutingContext:
    """Use existing Geoapify place resolution only for missing airport/hotel points."""

    if provider is None:
        return context
    requests: dict[tuple[str, str, str], list[RoutingPoint]] = {}
    arrival_city = context.days[0].city
    requests.setdefault(
        (context.arrival.point.name, arrival_city, context.trip_plan.destination),
        [],
    ).append(context.arrival.point)
    if context.departure is not None:
        departure_city = context.days[-1].city
        requests.setdefault(
            (
                context.departure.point.name,
                departure_city,
                context.trip_plan.destination,
            ),
            [],
        ).append(context.departure.point)
    for day in context.days:
        if not day.hotel_point.has_coordinates:
            key = (day.hotel.name, day.city, context.trip_plan.destination)
            requests.setdefault(key, []).append(day.hotel_point)

    semaphore = asyncio.Semaphore(LOCATION_RESOLUTION_CONCURRENCY)

    async def resolve(key: tuple[str, str, str]):
        name, city, destination = key
        async with semaphore:
            try:
                return await provider.resolve_place(
                    name=name,
                    location_hint=f"{name}, {city}, {destination}",
                    city=city,
                    destination=destination,
                )
            except Exception:
                return None

    keys = list(requests)
    outcomes = await asyncio.gather(*(resolve(key) for key in keys))
    resolved_context = context
    for key, outcome in zip(keys, outcomes):
        if outcome is None or outcome.status != "resolved" or outcome.place is None:
            continue
        for point in requests[key]:
            resolved_context = with_resolved_point(
                resolved_context,
                stop_id=point.stop_id,
                latitude=outcome.place.latitude,
                longitude=outcome.place.longitude,
                name=outcome.place.name,
            )
    return resolved_context


def _validated_state_model(value: object, model_type: type):
    if value is None:
        return None
    try:
        return model_type.model_validate(value)
    except Exception:
        return None


async def _close_provider(provider: object | None) -> None:
    if provider is None:
        return
    close = getattr(provider, "aclose", None)
    if close is None:
        return
    result = close()
    if isawaitable(result):
        await result
