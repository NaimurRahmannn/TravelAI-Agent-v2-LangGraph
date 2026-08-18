import asyncio

from app.core.logging import get_logger
from app.models import TripPlan
from app.services.places import (
    PlaceResolution,
    PlacesProvider,
    build_place_query,
    normalize_place_text,
)

logger = get_logger(__name__)

DEFAULT_PLACE_RESOLUTION_CONCURRENCY = 5


async def enrich_trip_places(
    trip_plan: TripPlan,
    provider: PlacesProvider,
    *,
    concurrency_limit: int = DEFAULT_PLACE_RESOLUTION_CONCURRENCY,
) -> TripPlan:
    """Return a copy of a trip plan enriched with provider-backed places."""

    semaphore = asyncio.Semaphore(max(1, concurrency_limit))
    tasks: dict[str, asyncio.Task[PlaceResolution]] = {}
    activity_keys: list[tuple[int, int, str]] = []

    async def resolve(
        *,
        name: str,
        location_hint: str | None,
        city: str,
    ) -> PlaceResolution:
        async with semaphore:
            try:
                return await provider.resolve_place(
                    name=name,
                    location_hint=location_hint,
                    city=city,
                    destination=trip_plan.destination,
                )
            except Exception as exc:
                logger.warning(
                    "place_resolution_provider_error activity=%s city=%s "
                    "destination=%s error_type=%s",
                    name,
                    city,
                    trip_plan.destination,
                    type(exc).__name__,
                )
                return PlaceResolution.unresolved()

    for day_index, day in enumerate(trip_plan.days):
        for activity_index, activity in enumerate(day.activities):
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
    for day_index, activity_index, cache_key in activity_keys:
        resolution = tasks[cache_key].result()
        activity_data = plan_data["days"][day_index]["activities"][activity_index]
        activity_data["place"] = (
            resolution.place.model_dump() if resolution.place is not None else None
        )
        activity_data["place_resolution_status"] = resolution.status

    return TripPlan.model_validate(plan_data)
