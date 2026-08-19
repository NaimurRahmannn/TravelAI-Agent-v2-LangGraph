import asyncio

from app.core.logging import get_logger
from app.models import Activity, PlaceImage, ResolvedPlace, TripPlan
from app.services.images import (
    ImageProviderUnavailableError,
    PlaceImageProvider,
)
from app.services.place_enrichment import should_resolve_activity_place
from app.services.places import normalize_place_text, place_name_variants

logger = get_logger(__name__)

DEFAULT_IMAGE_RESOLUTION_CONCURRENCY = 3


async def enrich_trip_images(
    trip_plan: TripPlan,
    provider: PlaceImageProvider,
    *,
    concurrency_limit: int = DEFAULT_IMAGE_RESOLUTION_CONCURRENCY,
) -> TripPlan:
    """Return a copy of a trip plan with trusted place-image metadata."""

    semaphore = asyncio.Semaphore(max(1, concurrency_limit))
    probe_lock = asyncio.Lock()
    tasks: dict[str, asyncio.Task[PlaceImage | None]] = {}
    activity_keys: list[tuple[int, int, str]] = []
    provider_checked = False
    circuit_open = False

    async def call_provider(place: ResolvedPlace) -> PlaceImage | None:
        nonlocal circuit_open

        try:
            return await provider.resolve_image(place=place)
        except ImageProviderUnavailableError as exc:
            if not circuit_open:
                logger.warning(
                    "image_provider_circuit_opened provider_place_id=%s "
                    "error_type=%s",
                    place.provider_place_id,
                    type(exc).__name__,
                )
            circuit_open = True
            return None
        except Exception as exc:
            logger.warning(
                "image_resolution_error provider_place_id=%s error_type=%s",
                place.provider_place_id,
                type(exc).__name__,
            )
            return None

    async def resolve(place: ResolvedPlace) -> PlaceImage | None:
        nonlocal provider_checked

        if circuit_open:
            return None

        # Probe once so an outage cannot multiply across all trip activities.
        if not provider_checked:
            async with probe_lock:
                if circuit_open:
                    return None
                if not provider_checked:
                    image = await call_provider(place)
                    provider_checked = True
                    return image

        async with semaphore:
            if circuit_open:
                return None
            return await call_provider(place)

    logger.info("image_enrichment_started destination=%s", trip_plan.destination)
    for day_index, day in enumerate(trip_plan.days):
        for activity_index, activity in enumerate(day.activities):
            if not should_enrich_activity_image(activity):
                logger.info(
                    "image_resolution_skipped activity=%s reason=ineligible",
                    activity.name,
                )
                continue
            place = activity.place
            if place is None:
                continue
            requested_name = activity.place_search_name or activity.name
            name_variants = place_name_variants(requested_name)
            lookup_name = (
                name_variants[1] if len(name_variants) > 1 else name_variants[0]
            )
            lookup_place = place.model_copy(update={"name": lookup_name})
            cache_key = image_deduplication_key(place)
            if cache_key not in tasks:
                tasks[cache_key] = asyncio.create_task(resolve(lookup_place))
            activity_keys.append((day_index, activity_index, cache_key))

    if tasks:
        await asyncio.gather(*tasks.values())

    # Provider metadata is the only trusted source, so discard any prior value.
    plan_data = trip_plan.model_dump()
    for day in plan_data["days"]:
        for activity in day["activities"]:
            activity["image"] = None
    for day_index, activity_index, cache_key in activity_keys:
        image = tasks[cache_key].result()
        if image is not None:
            plan_data["days"][day_index]["activities"][activity_index]["image"] = (
                image.model_dump()
            )

    return TripPlan.model_validate(plan_data)


def should_enrich_activity_image(activity: Activity) -> bool:
    """Return whether an activity has a trusted image-resolution identity."""

    return bool(
        should_resolve_activity_place(activity)
        and activity.place is not None
        and activity.place.provider == "geoapify"
        and activity.place.resolution_status == "resolved"
        and activity.place_resolution_status == "resolved"
    )


def has_image_eligible_activities(trip_plan: TripPlan) -> bool:
    """Return whether a plan can benefit from constructing an image provider."""

    return any(
        should_enrich_activity_image(activity)
        for day in trip_plan.days
        for activity in day.activities
    )


def image_deduplication_key(place: ResolvedPlace) -> str:
    """Build a request-local identity key, preferring the provider's ID."""

    if place.provider_place_id.strip():
        return f"{place.provider}|{place.provider_place_id.strip()}"
    fallback = normalize_place_text(
        f"{place.name} {place.latitude:.5f} {place.longitude:.5f}"
    )
    return f"{place.provider}|{fallback}"
