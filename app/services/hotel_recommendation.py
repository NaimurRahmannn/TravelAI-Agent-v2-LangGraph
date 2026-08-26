import asyncio
from dataclasses import dataclass
from datetime import date

from app.core.logging import get_logger
from app.models import (
    HotelOption,
    HotelSearchRequest,
    ItineraryDay,
    RecommendationDomainState,
    TravelRecommendations,
    TripPlan,
    build_hotel_stay_key,
)
from app.services.places.base import PlacesProvider, normalize_place_text
from app.services.recommendations import build_recommendation_status, rank_hotels
from app.services.recommendations.base import HotelProvider

logger = get_logger(__name__)

HOTEL_SEARCH_RADIUS_METERS = 5_000
MAX_HOTEL_STAY_SEARCHES = 10
MAX_HOTEL_RESULTS_TO_CONSIDER_PER_STAY = 20
MAX_HOTEL_RECOMMENDATIONS_PER_STAY = 3
HOTEL_SEARCH_CONCURRENCY = 2


@dataclass(frozen=True)
class HotelStay:
    city: str
    check_in: date
    check_out: date
    adults: int
    day_numbers: tuple[int, ...]

    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days

    @property
    def stay_key(self) -> str:
        return build_hotel_stay_key(self.city, self.check_in, self.check_out)


@dataclass(frozen=True)
class HotelSearchAnchor:
    latitude: float
    longitude: float


@dataclass(frozen=True)
class _StaySearchOutcome:
    index: int
    succeeded: bool
    provider_result_count: int = 0
    options: tuple[HotelOption, ...] = ()


def derive_hotel_stays(trip_plan: TripPlan) -> list[HotelStay]:
    """Group consecutive dated itinerary cities into non-overlapping stays."""

    if trip_plan.end_date is None or not trip_plan.days:
        return []
    days = sorted(trip_plan.days, key=lambda day: day.day_number)
    if any(day.date is None for day in days):
        return []

    groups: list[list[ItineraryDay]] = []
    for day in days:
        previous_city = normalize_place_text(groups[-1][0].city) if groups else None
        if previous_city != normalize_place_text(day.city):
            groups.append([day])
        else:
            groups[-1].append(day)

    stays: list[HotelStay] = []
    for index, group in enumerate(groups):
        first_day = group[0]
        check_in = first_day.date
        check_out = (
            groups[index + 1][0].date
            if index + 1 < len(groups)
            else trip_plan.end_date
        )
        if check_in is None or check_out is None or check_out <= check_in:
            continue
        stays.append(
            HotelStay(
                city=first_day.city,
                check_in=check_in,
                check_out=check_out,
                adults=trip_plan.travelers,
                day_numbers=tuple(day.day_number for day in group),
            )
        )
    return stays


async def enrich_hotel_recommendations(
    trip_plan: TripPlan,
    provider: HotelProvider,
    *,
    anchor_provider: PlacesProvider | None = None,
) -> TripPlan:
    """Search bounded hotel stays without changing itinerary budget or flights."""

    stays = derive_hotel_stays(trip_plan)
    nationality = trip_plan.guest_nationality_country_code
    if not stays:
        return update_hotel_recommendations(
            trip_plan,
            hotels=[],
            status=build_recommendation_status(searched=False),
        )
    if len(stays) > MAX_HOTEL_STAY_SEARCHES:
        logger.warning(
            "hotel_recommendations_unavailable reason=stay_limit_exceeded "
            "stay_count=%s stay_limit=%s",
            len(stays),
            MAX_HOTEL_STAY_SEARCHES,
        )
        return update_hotel_recommendations(
            trip_plan,
            hotels=[],
            status=build_recommendation_status(provider_available=False),
        )
    if nationality is None:
        logger.info("hotel_recommendations_unavailable reason=nationality_required")
        return update_hotel_recommendations(
            trip_plan,
            hotels=[],
            status=build_recommendation_status(provider_available=False),
        )

    logger.info("hotel_stays_derived stay_count=%s", len(stays))
    semaphore = asyncio.Semaphore(HOTEL_SEARCH_CONCURRENCY)

    async def search_stay(index: int, stay: HotelStay) -> _StaySearchOutcome:
        async with semaphore:
            try:
                anchor = _trusted_stay_anchor(trip_plan, stay)
                if anchor is None and anchor_provider is not None:
                    anchor = await _resolve_stay_anchor(
                        stay,
                        trip_plan.destination,
                        anchor_provider,
                    )
                if anchor is None:
                    logger.warning(
                        "hotel_stay_skipped city=%s reason=missing_trusted_anchor",
                        stay.city,
                    )
                    return _StaySearchOutcome(index=index, succeeded=False)

                request = HotelSearchRequest(
                    city=stay.city,
                    latitude=anchor.latitude,
                    longitude=anchor.longitude,
                    check_in=stay.check_in,
                    check_out=stay.check_out,
                    adults=stay.adults,
                    guest_nationality_country_code=nationality,
                    radius_meters=HOTEL_SEARCH_RADIUS_METERS,
                )
                logger.info(
                    "hotel_search_started city=%s check_in=%s check_out=%s",
                    stay.city,
                    stay.check_in,
                    stay.check_out,
                )
                options = await provider.search_hotels(request)
                bounded = options[:MAX_HOTEL_RESULTS_TO_CONSIDER_PER_STAY]
                selected = rank_hotels(bounded)[
                    :MAX_HOTEL_RECOMMENDATIONS_PER_STAY
                ]
                logger.info(
                    "hotel_search_completed city=%s provider_count=%s "
                    "selected_count=%s",
                    stay.city,
                    len(options),
                    len(selected),
                )
                return _StaySearchOutcome(
                    index=index,
                    succeeded=True,
                    provider_result_count=len(options),
                    options=tuple(selected),
                )
            except Exception as exc:
                logger.warning(
                    "hotel_search_failed city=%s error_type=%s",
                    stay.city,
                    type(exc).__name__,
                )
                return _StaySearchOutcome(index=index, succeeded=False)

    outcomes = await asyncio.gather(
        *(search_stay(index, stay) for index, stay in enumerate(stays))
    )
    outcomes.sort(key=lambda outcome: outcome.index)
    hotels = [option for outcome in outcomes for option in outcome.options]
    succeeded = [outcome for outcome in outcomes if outcome.succeeded]
    if hotels:
        status = build_recommendation_status(
            provider_result_count=sum(
                outcome.provider_result_count for outcome in outcomes
            )
        )
    elif succeeded:
        status = build_recommendation_status(provider_result_count=0)
    else:
        status = build_recommendation_status(provider_available=False)
    return update_hotel_recommendations(
        trip_plan,
        hotels=hotels,
        status=status,
    )


def mark_hotel_recommendations_unavailable(trip_plan: TripPlan) -> TripPlan:
    """Record missing configuration or a provider-wide hotel outage."""

    status = (
        build_recommendation_status(provider_available=False)
        if derive_hotel_stays(trip_plan)
        else build_recommendation_status(searched=False)
    )
    return update_hotel_recommendations(trip_plan, hotels=[], status=status)


def update_hotel_recommendations(
    trip_plan: TripPlan,
    *,
    hotels: list[HotelOption],
    status: RecommendationDomainState,
) -> TripPlan:
    """Replace only hotel results, preserving flight and restaurant state."""

    recommendations = (
        trip_plan.recommendations.model_copy(deep=True)
        if trip_plan.recommendations is not None
        else TravelRecommendations()
    )
    recommendations.hotels = list(hotels)
    recommendations.hotel_status = status
    return trip_plan.model_copy(update={"recommendations": recommendations})


def _trusted_stay_anchor(
    trip_plan: TripPlan,
    stay: HotelStay,
) -> HotelSearchAnchor | None:
    day_numbers = set(stay.day_numbers)
    candidates = []
    for day in trip_plan.days:
        if day.day_number not in day_numbers:
            continue
        for activity in day.activities:
            place = activity.place
            if (
                place is None
                or activity.place_resolution_status != "resolved"
                or place.resolution_status != "resolved"
                or not _is_usable_anchor(place.latitude, place.longitude)
            ):
                continue
            candidates.append(
                (
                    _is_logistics_activity(activity.name, activity.category),
                    day.day_number,
                    place.provider_place_id,
                    HotelSearchAnchor(place.latitude, place.longitude),
                )
            )
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    return candidates[0][3]


async def _resolve_stay_anchor(
    stay: HotelStay,
    destination: str,
    provider: PlacesProvider,
) -> HotelSearchAnchor | None:
    resolution = await provider.resolve_place(
        name=stay.city,
        location_hint=f"{stay.city}, {destination}",
        city=stay.city,
        destination=destination,
    )
    if resolution.status != "resolved" or resolution.place is None:
        return None
    if not _is_usable_anchor(
        resolution.place.latitude,
        resolution.place.longitude,
    ):
        return None
    return HotelSearchAnchor(
        resolution.place.latitude,
        resolution.place.longitude,
    )


def _is_logistics_activity(name: str, category: str) -> bool:
    text = f"{name} {category}".casefold()
    return any(
        term in text
        for term in (
            "airport",
            "flight",
            "hotel check",
            "lodging",
            "transfer",
            "transport",
        )
    )


def _is_usable_anchor(latitude: float, longitude: float) -> bool:
    return not (latitude == 0 and longitude == 0)
