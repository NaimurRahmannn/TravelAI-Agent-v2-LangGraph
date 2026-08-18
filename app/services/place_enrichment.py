import asyncio
import re

from app.core.logging import get_logger
from app.models import Activity, TripPlan
from app.services.places import (
    PlaceResolution,
    PlacesProvider,
    PlacesProviderUnavailableError,
    build_place_query,
    normalize_place_text,
)

logger = get_logger(__name__)

DEFAULT_PLACE_RESOLUTION_CONCURRENCY = 5

NON_PLACE_CATEGORY_TERMS = frozenset(
    {
        "accommodation",
        "arrival",
        "bus",
        "car",
        "departure",
        "dining",
        "ferry",
        "flight",
        "food",
        "hotel",
        "lodging",
        "logistics",
        "meal",
        "restaurant",
        "taxi",
        "train",
        "transfer",
        "transit",
        "transport",
        "transportation",
    }
)
NON_PLACE_NAME_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"\btransfer\b",
        r"^(?:train|bus|flight|ferry|drive|travel|return)\s+(?:to|from)\b",
        r"\bcheck\s+(?:in|out)\b",
        r"^(?:arrival|departure)\b",
        r"^(?:breakfast|lunch|dinner|meal)\b",
    )
)


async def enrich_trip_places(
    trip_plan: TripPlan,
    provider: PlacesProvider,
    *,
    concurrency_limit: int = DEFAULT_PLACE_RESOLUTION_CONCURRENCY,
) -> TripPlan:
    """Return a copy of a trip plan enriched with provider-backed places."""

    semaphore = asyncio.Semaphore(max(1, concurrency_limit))
    probe_lock = asyncio.Lock()
    tasks: dict[str, asyncio.Task[PlaceResolution]] = {}
    activity_keys: list[tuple[int, int, str]] = []
    skipped_activities: list[tuple[int, int]] = []
    provider_checked = False
    circuit_open = False

    async def call_provider(
        *,
        name: str,
        location_hint: str | None,
        city: str,
    ) -> PlaceResolution:
        nonlocal circuit_open

        try:
            return await provider.resolve_place(
                name=name,
                location_hint=location_hint,
                city=city,
                destination=trip_plan.destination,
            )
        except PlacesProviderUnavailableError as exc:
            if not circuit_open:
                logger.warning(
                    "place_resolution_circuit_open activity=%s city=%s "
                    "destination=%s error_type=%s",
                    name,
                    city,
                    trip_plan.destination,
                    type(exc).__name__,
                )
            circuit_open = True
            return PlaceResolution.unresolved()
        except Exception as exc:
            logger.warning(
                "place_resolution_activity_error activity=%s city=%s "
                "destination=%s error_type=%s",
                name,
                city,
                trip_plan.destination,
                type(exc).__name__,
            )
            return PlaceResolution.unresolved()

    async def resolve(
        *,
        name: str,
        location_hint: str | None,
        city: str,
    ) -> PlaceResolution:
        nonlocal provider_checked

        if circuit_open:
            return PlaceResolution.unresolved()

        # Probe provider health once before releasing concurrent requests. This
        # prevents a bad credential or outage from multiplying across a trip.
        if not provider_checked:
            async with probe_lock:
                if circuit_open:
                    return PlaceResolution.unresolved()
                if not provider_checked:
                    resolution = await call_provider(
                        name=name,
                        location_hint=location_hint,
                        city=city,
                    )
                    provider_checked = True
                    return resolution

        async with semaphore:
            if circuit_open:
                return PlaceResolution.unresolved()
            return await call_provider(
                name=name,
                location_hint=location_hint,
                city=city,
            )

    for day_index, day in enumerate(trip_plan.days):
        for activity_index, activity in enumerate(day.activities):
            if not should_resolve_activity_place(activity):
                logger.info(
                    "place_resolution_skipped activity=%s category=%s reason=non_place",
                    activity.name,
                    activity.category,
                )
                skipped_activities.append((day_index, activity_index))
                continue

            query = build_place_query(
                name=activity.name,
                location_hint=activity.location_hint,
                city=day.city,
                destination=trip_plan.destination,
            )
            cache_key = normalize_place_text(query)
            if cache_key not in tasks:
                tasks[cache_key] = asyncio.create_task(
                    resolve(
                        name=activity.name,
                        location_hint=activity.location_hint,
                        city=day.city,
                    )
                )
            activity_keys.append((day_index, activity_index, cache_key))

    if tasks:
        await asyncio.gather(*tasks.values())

    plan_data = trip_plan.model_dump()
    for day_index, activity_index in skipped_activities:
        activity_data = plan_data["days"][day_index]["activities"][activity_index]
        activity_data["place"] = None
        activity_data["place_resolution_status"] = "unresolved"

    for day_index, activity_index, cache_key in activity_keys:
        resolution = tasks[cache_key].result()
        activity_data = plan_data["days"][day_index]["activities"][activity_index]
        activity_data["place"] = (
            resolution.place.model_dump() if resolution.place is not None else None
        )
        activity_data["place_resolution_status"] = resolution.status

    return TripPlan.model_validate(plan_data)


def should_resolve_activity_place(activity: Activity) -> bool:
    """Return whether an activity represents a place suitable for geocoding."""

    category = normalize_place_text(activity.category)
    category_tokens = set(category.split())
    if category_tokens & NON_PLACE_CATEGORY_TERMS:
        return False

    name = normalize_place_text(activity.name)
    return not any(pattern.search(name) for pattern in NON_PLACE_NAME_PATTERNS)
