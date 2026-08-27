from datetime import UTC, datetime, timedelta
from inspect import isawaitable

from app.core.logging import get_logger
from app.models import (
    FlightOption,
    FlightSearchCache,
    FlightSearchRequest,
    FlightSearchScope,
    RecommendationDomainState,
    TravelRecommendations,
    TripPlan,
)
from app.services.recommendations import (
    build_recommendation_status,
    rank_flights,
)
from app.services.recommendations.base import FlightProvider
from app.services.recommendations.flights import (
    GeoapifyAirportResolver,
    SwoopFlightProvider,
)

logger = get_logger(__name__)

MAX_FLIGHT_RECOMMENDATIONS = 5
FLIGHT_SEARCH_CACHE_TTL_SECONDS = 15 * 60
FLIGHT_SEARCH_CACHE_TTL = timedelta(seconds=FLIGHT_SEARCH_CACHE_TTL_SECONDS)
CACHEABLE_FLIGHT_STATUSES = frozenset({"available", "no_results"})


async def enrich_flight_recommendations(
    trip_plan: TripPlan,
    provider: FlightProvider,
) -> TripPlan:
    """Search and rank provider flights independently of itinerary budget."""

    request = build_flight_search_request(trip_plan)
    if request is None:
        return update_flight_recommendations(
            trip_plan,
            flights=[],
            status=build_recommendation_status(searched=False),
        )

    return await search_flight_recommendations(trip_plan, request, provider)


async def search_flight_recommendations(
    trip_plan: TripPlan,
    request: FlightSearchRequest,
    provider: FlightProvider,
) -> TripPlan:
    """Search one authoritative request and attach ranked normalized results."""

    provider_options = await provider.search_flights(request)
    if not provider_options:
        return update_flight_recommendations(
            trip_plan,
            flights=[],
            status=build_recommendation_status(provider_result_count=0),
        )

    selected = rank_flights(provider_options)[:MAX_FLIGHT_RECOMMENDATIONS]
    status = build_recommendation_status(
        provider_result_count=len(provider_options),
    )
    logger.info(
        "flight_recommendations_ranked provider_count=%s selected_count=%s status=%s",
        len(provider_options),
        len(selected),
        status.status,
    )
    return update_flight_recommendations(
        trip_plan,
        flights=selected,
        status=status,
    )


def flight_requests_match(
    cached_request: FlightSearchRequest,
    current_request: FlightSearchRequest,
) -> bool:
    """Compare every normalized request field, including future additions."""

    return cached_request.model_dump(mode="json") == current_request.model_dump(
        mode="json"
    )


def is_flight_cache_fresh(
    cache: FlightSearchCache,
    now: datetime,
) -> bool:
    """Return whether a cache timestamp is valid and inside the planning TTL."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Flight cache comparison time must be timezone-aware")
    age = now.astimezone(UTC) - cache.searched_at
    return timedelta(0) <= age <= FLIGHT_SEARCH_CACHE_TTL


def can_reuse_flight_cache(
    cache: FlightSearchCache | None,
    current_request: FlightSearchRequest,
    now: datetime,
) -> bool:
    """Return whether one successful normalized search can be reattached."""

    return bool(
        cache is not None
        and cache.status.status in CACHEABLE_FLIGHT_STATUSES
        and flight_requests_match(cache.request, current_request)
        and is_flight_cache_fresh(cache, now)
    )


def build_flight_search_cache(
    request: FlightSearchRequest,
    trip_plan: TripPlan,
    *,
    searched_at: datetime | None = None,
) -> FlightSearchCache:
    """Persist only final application-normalized, cacheable flight results."""

    recommendations = trip_plan.recommendations
    if (
        recommendations is None
        or recommendations.flight_status.status not in CACHEABLE_FLIGHT_STATUSES
    ):
        raise ValueError("Only successful flight search outcomes can be cached")
    return FlightSearchCache(
        request=request,
        flights=recommendations.flights,
        status=recommendations.flight_status,
        searched_at=searched_at or datetime.now(UTC),
    )


def build_flight_provider(geoapify_api_key: str) -> FlightProvider:
    """Construct Swoop with the existing Geoapify airport resolver."""

    return SwoopFlightProvider(GeoapifyAirportResolver(geoapify_api_key))


async def close_flight_provider(provider: FlightProvider) -> None:
    """Close a provider when it exposes a synchronous or asynchronous close."""

    close = getattr(provider, "aclose", None)
    if close is None:
        return
    result = close()
    if isawaitable(result):
        await result


def build_flight_search_request(
    trip_plan: TripPlan,
    *,
    scope: FlightSearchScope = "round_trip",
) -> FlightSearchRequest | None:
    """Build a scoped adults-only search from authoritative itinerary endpoints."""

    if (
        not trip_plan.origin
        or not trip_plan.destination
        or trip_plan.start_date is None
        or trip_plan.end_date is None
        or trip_plan.travelers < 1
        or not trip_plan.days
    ):
        return None

    first_day = min(trip_plan.days, key=lambda day: day.day_number)
    last_day = max(trip_plan.days, key=lambda day: day.day_number)
    first_city = first_day.city.strip() or trip_plan.destination
    last_city = last_day.city.strip() or trip_plan.destination
    if scope == "return":
        return FlightSearchRequest(
            origin=last_city,
            destination=trip_plan.origin,
            origin_country_hint=_day_country_code(last_day),
            destination_country_hint=_explicit_country_code(trip_plan.origin),
            departure_date=trip_plan.end_date,
            adults=trip_plan.travelers,
        )

    return FlightSearchRequest(
        origin=trip_plan.origin,
        destination=first_city,
        return_origin=last_city if scope == "round_trip" else None,
        return_destination=trip_plan.origin if scope == "round_trip" else None,
        origin_country_hint=_explicit_country_code(trip_plan.origin),
        destination_country_hint=_day_country_code(first_day),
        return_origin_country_hint=(
            _day_country_code(last_day) if scope == "round_trip" else None
        ),
        return_destination_country_hint=(
            _explicit_country_code(trip_plan.origin)
            if scope == "round_trip"
            else None
        ),
        departure_date=trip_plan.start_date,
        return_date=trip_plan.end_date if scope == "round_trip" else None,
        adults=trip_plan.travelers,
    )


def mark_flight_recommendations_unavailable(
    trip_plan: TripPlan,
    *,
    scope: FlightSearchScope = "round_trip",
) -> TripPlan:
    """Record an optional provider outage while retaining every other result."""

    status = (
        build_recommendation_status(provider_available=False)
        if build_flight_search_request(trip_plan, scope=scope) is not None
        else build_recommendation_status(searched=False)
    )
    return update_flight_recommendations(trip_plan, flights=[], status=status)


def update_flight_recommendations(
    trip_plan: TripPlan,
    *,
    flights: list[FlightOption],
    status: RecommendationDomainState,
) -> TripPlan:
    """Replace only flight results, preserving future hotel/restaurant state."""

    recommendations = (
        trip_plan.recommendations.model_copy(deep=True)
        if trip_plan.recommendations is not None
        else TravelRecommendations()
    )
    recommendations.flights = list(flights)
    recommendations.flight_status = status
    return trip_plan.model_copy(update={"recommendations": recommendations})


def _day_country_code(day: object) -> str | None:
    activities = getattr(day, "activities", [])
    for activity in activities:
        place = getattr(activity, "place", None)
        country_code = getattr(place, "country_code", None)
        normalized = _explicit_country_code(country_code)
        if normalized:
            return normalized
    return None


def _explicit_country_code(value: str | None) -> str | None:
    normalized = value.strip().upper() if value else ""
    return normalized if len(normalized) == 2 and normalized.isalpha() else None
