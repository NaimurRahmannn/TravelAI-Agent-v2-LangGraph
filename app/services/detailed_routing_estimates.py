import asyncio
import json
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from app.llm import get_gemini_llm
from app.models import DetailedRouteLeg, RouteTimeEstimate
from app.services.detailed_routing_context import (
    DetailedRoutingContext,
    RequiredRouteLeg,
    RoutingActivity,
    straight_line_distance_km,
)
from app.services.routing import (
    RouteResult,
    RoutingProvider,
)

DETAIL_ROUTE_CONCURRENCY = 3
MAX_PLANNING_MINUTES = 360
MIN_VISIT_MINUTES = 15
DEFAULT_ACTIVITY_DURATION_MINUTES = 60

RouteCacheKey = tuple[float, float, float, float, str]


class LlmRouteEstimate(BaseModel):
    """One range-only route estimate with no schedule fields by design."""

    model_config = ConfigDict(extra="forbid")

    leg_id: str
    minimum_minutes: int
    maximum_minutes: int
    brief_reason: str


class ActivityVisitEstimate(BaseModel):
    """One range-only suggested visit duration."""

    model_config = ConfigDict(extra="forbid")

    activity_id: str
    minimum_minutes: int
    maximum_minutes: int
    brief_reason: str


class DetailedRoutingPlanningEstimates(BaseModel):
    """Single batched planning response for all unresolved route and visit times."""

    model_config = ConfigDict(extra="forbid")

    route_estimates: list[LlmRouteEstimate]
    activity_estimates: list[ActivityVisitEstimate]


class DetailedPlanningEstimator(Protocol):
    async def estimate(
        self,
        *,
        missing_routes: list[dict[str, object]],
        activities: list[dict[str, object]],
    ) -> DetailedRoutingPlanningEstimates:
        """Return one combined batch of planning ranges."""


class GeminiDetailedPlanningEstimator:
    """Use Gemini only for explicitly labeled range estimates."""

    async def estimate(
        self,
        *,
        missing_routes: list[dict[str, object]],
        activities: list[dict[str, object]],
    ) -> DetailedRoutingPlanningEstimates:
        structured = get_gemini_llm().with_structured_output(
            DetailedRoutingPlanningEstimates,
            method="json_schema",
        )
        response = await structured.ainvoke(
            [
                SystemMessage(
                    content=(
                        "You generate conservative travel-planning ranges, not live "
                        "route facts. For each supplied route, estimate a reasonable "
                        "duration range using only its names, city, requested mode, "
                        "coordinates, straight-line distance, and approximate time. "
                        "Never invent stations, transit lines, train or bus numbers, "
                        "departure schedules, real-time traffic, or live availability. "
                        "For each activity, estimate a practical visit-duration range. "
                        "Return every supplied ID exactly once and structured data only."
                    )
                ),
                HumanMessage(
                    content=json.dumps(
                        {
                            "missing_route_legs": missing_routes,
                            "activities": activities,
                        },
                        separators=(",", ":"),
                    )
                ),
            ]
        )
        return DetailedRoutingPlanningEstimates.model_validate(response)


@dataclass(frozen=True)
class VisitDuration:
    minimum_minutes: int
    maximum_minutes: int
    planning_minutes: int
    source: str
    reason: str | None = None


@dataclass(frozen=True)
class PlanningEstimateBundle:
    route_legs: dict[str, DetailedRouteLeg]
    visit_durations: dict[str, VisitDuration]
    geoapify_success_count: int
    geoapify_failure_count: int
    llm_route_count: int
    llm_activity_count: int


async def build_planning_estimates(
    context: DetailedRoutingContext,
    required_legs: list[RequiredRouteLeg],
    *,
    routing_provider: RoutingProvider | None,
    planning_estimator: DetailedPlanningEstimator | None,
) -> PlanningEstimateBundle:
    """Resolve provider routes, then make at most one combined LLM call."""

    route_legs = await _resolve_geoapify_routes(required_legs, routing_provider)
    missing = [
        leg for leg in required_legs if route_legs[leg.leg_id].duration.source == "unavailable"
    ]
    activities = [
        activity
        for day in context.days
        for activity in day.activities
        if explicit_activity_duration(activity) is None
    ]
    route_estimates: dict[str, LlmRouteEstimate] = {}
    activity_estimates: dict[str, ActivityVisitEstimate] = {}
    if planning_estimator is not None and (missing or activities):
        try:
            response = await planning_estimator.estimate(
                missing_routes=[_route_prompt_input(leg, context) for leg in missing],
                activities=[
                    _activity_prompt_input(activity, context) for activity in activities
                ],
            )
            route_estimates = {
                estimate.leg_id: estimate
                for estimate in response.route_estimates
                if _valid_range(
                    estimate.minimum_minutes,
                    estimate.maximum_minutes,
                    lower_bound=1,
                )
            }
            activity_estimates = {
                estimate.activity_id: estimate
                for estimate in response.activity_estimates
                if _valid_range(
                    estimate.minimum_minutes,
                    estimate.maximum_minutes,
                    lower_bound=MIN_VISIT_MINUTES,
                )
            }
        except Exception:
            route_estimates = {}
            activity_estimates = {}

    llm_route_count = 0
    for candidate in missing:
        estimate = route_estimates.get(candidate.leg_id)
        if estimate is None:
            continue
        route_legs[candidate.leg_id] = DetailedRouteLeg(
            leg_id=candidate.leg_id,
            origin_stop_id=candidate.origin.stop_id,
            destination_stop_id=candidate.destination.stop_id,
            origin_name=candidate.origin.name,
            destination_name=candidate.destination.name,
            requested_mode=candidate.requested_mode,
            resolved_mode=candidate.requested_mode,
            duration=RouteTimeEstimate(
                min_minutes=estimate.minimum_minutes,
                max_minutes=estimate.maximum_minutes,
                planning_minutes=estimate.maximum_minutes,
                source="llm_estimate",
                approximate=True,
            ),
            note=estimate.brief_reason,
        )
        llm_route_count += 1

    visit_durations: dict[str, VisitDuration] = {}
    llm_activity_count = 0
    for day in context.days:
        for activity in day.activities:
            explicit = explicit_activity_duration(activity)
            if explicit is not None:
                visit_durations[activity.activity_id] = explicit
                continue
            estimate = activity_estimates.get(activity.activity_id)
            if estimate is not None:
                visit_durations[activity.activity_id] = VisitDuration(
                    minimum_minutes=estimate.minimum_minutes,
                    maximum_minutes=estimate.maximum_minutes,
                    planning_minutes=estimate.maximum_minutes,
                    source="llm_estimate",
                    reason=estimate.brief_reason,
                )
                llm_activity_count += 1
            else:
                visit_durations[activity.activity_id] = VisitDuration(
                    minimum_minutes=DEFAULT_ACTIVITY_DURATION_MINUTES,
                    maximum_minutes=DEFAULT_ACTIVITY_DURATION_MINUTES,
                    planning_minutes=DEFAULT_ACTIVITY_DURATION_MINUTES,
                    source="planning_policy",
                    reason="Default visit duration used because no estimate was available.",
                )

    success_count = sum(
        leg.duration.source == "geoapify" for leg in route_legs.values()
    )
    return PlanningEstimateBundle(
        route_legs=route_legs,
        visit_durations=visit_durations,
        geoapify_success_count=success_count,
        geoapify_failure_count=len(required_legs) - success_count,
        llm_route_count=llm_route_count,
        llm_activity_count=llm_activity_count,
    )


async def _resolve_geoapify_routes(
    required_legs: list[RequiredRouteLeg],
    provider: RoutingProvider | None,
) -> dict[str, DetailedRouteLeg]:
    cache: dict[RouteCacheKey, RouteResult | None] = {}
    key_for_leg: dict[str, RouteCacheKey] = {}
    unique: dict[RouteCacheKey, RequiredRouteLeg] = {}
    for leg in required_legs:
        key = _route_key(leg)
        if key is not None:
            key_for_leg[leg.leg_id] = key
            unique.setdefault(key, leg)

    if provider is not None:
        semaphore = asyncio.Semaphore(DETAIL_ROUTE_CONCURRENCY)

        async def resolve(key: RouteCacheKey, leg: RequiredRouteLeg) -> None:
            async with semaphore:
                try:
                    assert leg.origin.latitude is not None
                    assert leg.origin.longitude is not None
                    assert leg.destination.latitude is not None
                    assert leg.destination.longitude is not None
                    cache[key] = await provider.get_route(
                        origin_latitude=leg.origin.latitude,
                        origin_longitude=leg.origin.longitude,
                        destination_latitude=leg.destination.latitude,
                        destination_longitude=leg.destination.longitude,
                        mode=leg.requested_mode,
                    )
                except Exception:
                    cache[key] = None

        await asyncio.gather(*(resolve(key, leg) for key, leg in unique.items()))

    results: dict[str, DetailedRouteLeg] = {}
    for leg in required_legs:
        route = cache.get(key_for_leg.get(leg.leg_id))
        if route is not None:
            minutes = max(1, math.ceil(route.duration_seconds / 60))
            results[leg.leg_id] = DetailedRouteLeg(
                leg_id=leg.leg_id,
                origin_stop_id=leg.origin.stop_id,
                destination_stop_id=leg.destination.stop_id,
                origin_name=leg.origin.name,
                destination_name=leg.destination.name,
                requested_mode=leg.requested_mode,
                resolved_mode=leg.requested_mode,
                distance_km=round(route.distance_meters / 1000, 2),
                duration=RouteTimeEstimate(
                    min_minutes=minutes,
                    max_minutes=minutes,
                    planning_minutes=minutes,
                    source="geoapify",
                ),
                provider="geoapify",
            )
        else:
            results[leg.leg_id] = DetailedRouteLeg(
                leg_id=leg.leg_id,
                origin_stop_id=leg.origin.stop_id,
                destination_stop_id=leg.destination.stop_id,
                origin_name=leg.origin.name,
                destination_name=leg.destination.name,
                requested_mode=leg.requested_mode,
                duration=RouteTimeEstimate(source="unavailable"),
                note="Routing information was unavailable for this leg.",
            )
    return results


def explicit_activity_duration(activity: RoutingActivity) -> VisitDuration | None:
    start = _parse_clock(activity.activity.start_time)
    end = _parse_clock(activity.activity.end_time)
    if start is None or end is None:
        return None
    start_minutes = start.hour * 60 + start.minute
    end_minutes = end.hour * 60 + end.minute
    duration = end_minutes - start_minutes
    if not MIN_VISIT_MINUTES <= duration <= MAX_PLANNING_MINUTES:
        return None
    return VisitDuration(
        minimum_minutes=duration,
        maximum_minutes=duration,
        planning_minutes=duration,
        source="itinerary",
    )


def _parse_clock(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip().upper()
    for pattern in ("%H:%M", "%I:%M %p", "%I %p"):
        try:
            return datetime.strptime(normalized, pattern)
        except ValueError:
            continue
    return None


def _valid_range(minimum: int, maximum: int, *, lower_bound: int) -> bool:
    return lower_bound <= minimum <= maximum <= MAX_PLANNING_MINUTES


def _route_key(leg: RequiredRouteLeg) -> RouteCacheKey | None:
    if not leg.origin.has_coordinates or not leg.destination.has_coordinates:
        return None
    assert leg.origin.latitude is not None and leg.origin.longitude is not None
    assert leg.destination.latitude is not None
    assert leg.destination.longitude is not None
    return (
        round(leg.origin.latitude, 6),
        round(leg.origin.longitude, 6),
        round(leg.destination.latitude, 6),
        round(leg.destination.longitude, 6),
        leg.requested_mode,
    )


def _route_prompt_input(
    leg: RequiredRouteLeg,
    context: DetailedRoutingContext,
) -> dict[str, object]:
    day = next(day for day in context.days if day.day_number == leg.day_number)
    return {
        "leg_id": leg.leg_id,
        "origin": leg.origin.name,
        "destination": leg.destination.name,
        "city": day.city,
        "requested_mode": leg.requested_mode,
        "origin_coordinates": _coordinate_pair(leg.origin),
        "destination_coordinates": _coordinate_pair(leg.destination),
        "straight_line_distance_km": straight_line_distance_km(
            leg.origin,
            leg.destination,
        ),
    }


def _activity_prompt_input(
    activity: RoutingActivity,
    context: DetailedRoutingContext,
) -> dict[str, object]:
    day = next(
        day for day in context.days if activity in day.activities
    )
    return {
        "activity_id": activity.activity_id,
        "name": activity.activity.name,
        "category": activity.activity.category,
        "description": activity.activity.description,
        "city": day.city,
        "time_hint": activity.activity.start_time,
    }


def _coordinate_pair(point: object) -> list[float] | None:
    latitude = getattr(point, "latitude", None)
    longitude = getattr(point, "longitude", None)
    if latitude is None or longitude is None:
        return None
    return [latitude, longitude]
