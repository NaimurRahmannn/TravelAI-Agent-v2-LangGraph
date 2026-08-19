import asyncio
import math
from dataclasses import dataclass

from app.core.logging import get_logger
from app.models import Activity, ResolvedPlace, TravelLeg, TravelMode, TripPlan
from app.services.routing import (
    RouteResult,
    RoutingProvider,
    RoutingProviderError,
    RoutingProviderUnavailableError,
)

logger = get_logger(__name__)

DEFAULT_ROUTING_CONCURRENCY = 2
MAX_ROUTE_REQUESTS_PER_TRIP = 20
WALK_DISTANCE_THRESHOLD_KM = 1.5
SAME_PLACE_DISTANCE_THRESHOLD_KM = 0.01

RouteKey = tuple[float, float, float, float, TravelMode]


@dataclass(frozen=True)
class _LegCandidate:
    day_index: int
    from_activity_index: int
    from_activity: Activity
    to_activity: Activity
    mode: TravelMode
    key: RouteKey


async def enrich_trip_routes(
    trip_plan: TripPlan,
    provider: RoutingProvider,
    *,
    concurrency_limit: int = DEFAULT_ROUTING_CONCURRENCY,
    request_limit: int = MAX_ROUTE_REQUESTS_PER_TRIP,
) -> TripPlan:
    """Return a copy with trusted estimates for adjacent resolved activities."""

    candidates = _collect_candidates(trip_plan)
    unique_requests: dict[RouteKey, _LegCandidate] = {}
    for candidate in candidates:
        unique_requests.setdefault(candidate.key, candidate)

    selected = list(unique_requests.items())[: max(0, request_limit)]
    outcomes: dict[RouteKey, RouteResult | None] = {}
    circuit_open = False

    async def call_provider(candidate: _LegCandidate) -> RouteResult | None:
        nonlocal circuit_open

        if circuit_open:
            return None
        origin = candidate.from_activity.place
        destination = candidate.to_activity.place
        if origin is None or destination is None:
            return None
        try:
            return await provider.get_route(
                origin_latitude=origin.latitude,
                origin_longitude=origin.longitude,
                destination_latitude=destination.latitude,
                destination_longitude=destination.longitude,
                mode=candidate.mode,
            )
        except RoutingProviderUnavailableError as exc:
            if not circuit_open:
                logger.warning(
                    "routing_provider_circuit_opened error_type=%s",
                    type(exc).__name__,
                )
            circuit_open = True
            return None
        except RoutingProviderError as exc:
            logger.warning(
                "routing_leg_unavailable error_type=%s",
                type(exc).__name__,
            )
            return None
        except Exception as exc:
            logger.warning(
                "routing_leg_unavailable error_type=%s",
                type(exc).__name__,
            )
            return None

    logger.info(
        "routing_enrichment_started destination=%s eligible_legs=%s unique_requests=%s",
        trip_plan.destination,
        len(candidates),
        len(unique_requests),
    )

    # Probe once before parallel work so provider-wide failures do not fan out.
    if selected:
        first_key, first_candidate = selected[0]
        outcomes[first_key] = await call_provider(first_candidate)

    if len(selected) > 1 and not circuit_open:
        semaphore = asyncio.Semaphore(max(1, concurrency_limit))

        async def resolve(key: RouteKey, candidate: _LegCandidate) -> None:
            async with semaphore:
                outcomes[key] = await call_provider(candidate)

        await asyncio.gather(
            *(resolve(key, candidate) for key, candidate in selected[1:])
        )

    if len(unique_requests) > len(selected):
        logger.warning(
            "routing_request_limit_reached limit=%s skipped_unique_requests=%s",
            max(0, request_limit),
            len(unique_requests) - len(selected),
        )

    plan_data = trip_plan.model_dump()
    for day in plan_data["days"]:
        day["travel_legs"] = []
    for candidate in candidates:
        result = outcomes.get(candidate.key)
        leg = _build_travel_leg(candidate, result)
        plan_data["days"][candidate.day_index]["travel_legs"].append(
            leg.model_dump()
        )
    return TripPlan.model_validate(plan_data)


def has_routing_eligible_legs(trip_plan: TripPlan) -> bool:
    """Return whether the plan has a routeable adjacent activity pair."""

    return bool(_collect_candidates(trip_plan))


def choose_travel_mode(activity: Activity, distance_km: float) -> TravelMode:
    """Prefer the planning hint, otherwise use a deterministic distance rule."""

    if activity.travel_mode_to_next is not None:
        return activity.travel_mode_to_next
    return "walk" if distance_km <= WALK_DISTANCE_THRESHOLD_KM else "drive"


def haversine_distance_km(origin: ResolvedPlace, destination: ResolvedPlace) -> float:
    """Return straight-line distance between two resolved coordinates."""

    radius_km = 6371.0088
    latitude_1 = math.radians(origin.latitude)
    latitude_2 = math.radians(destination.latitude)
    delta_latitude = latitude_2 - latitude_1
    delta_longitude = math.radians(destination.longitude - origin.longitude)
    value = (
        math.sin(delta_latitude / 2) ** 2
        + math.cos(latitude_1)
        * math.cos(latitude_2)
        * math.sin(delta_longitude / 2) ** 2
    )
    return radius_km * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _collect_candidates(trip_plan: TripPlan) -> list[_LegCandidate]:
    candidates: list[_LegCandidate] = []
    for day_index, day in enumerate(trip_plan.days):
        for from_index in range(len(day.activities) - 1):
            origin_activity = day.activities[from_index]
            destination_activity = day.activities[from_index + 1]
            if not (
                _has_trusted_place(origin_activity)
                and _has_trusted_place(destination_activity)
            ):
                continue
            origin = origin_activity.place
            destination = destination_activity.place
            if origin is None or destination is None:
                continue
            distance_km = haversine_distance_km(origin, destination)
            if (
                origin.provider_place_id == destination.provider_place_id
                or distance_km <= SAME_PLACE_DISTANCE_THRESHOLD_KM
            ):
                continue
            mode = choose_travel_mode(origin_activity, distance_km)
            key = (
                round(origin.latitude, 6),
                round(origin.longitude, 6),
                round(destination.latitude, 6),
                round(destination.longitude, 6),
                mode,
            )
            candidates.append(
                _LegCandidate(
                    day_index=day_index,
                    from_activity_index=from_index,
                    from_activity=origin_activity,
                    to_activity=destination_activity,
                    mode=mode,
                    key=key,
                )
            )
    return candidates


def _has_trusted_place(activity: Activity) -> bool:
    place = activity.place
    return bool(
        place is not None
        and place.provider == "geoapify"
        and place.resolution_status == "resolved"
        and activity.place_resolution_status == "resolved"
    )


def _build_travel_leg(
    candidate: _LegCandidate,
    result: RouteResult | None,
) -> TravelLeg:
    return TravelLeg(
        provider="geoapify",
        from_activity_index=candidate.from_activity_index,
        to_activity_index=candidate.from_activity_index + 1,
        from_name=candidate.from_activity.name,
        to_name=candidate.to_activity.name,
        mode=candidate.mode,
        distance_meters=result.distance_meters if result else None,
        duration_seconds=result.duration_seconds if result else None,
        status="resolved" if result else "unavailable",
    )
