from app.core.logging import get_logger
from app.models import (
    FlightOption,
    FlightSearchRequest,
    RecommendationDomainState,
    TravelRecommendations,
    TripPlan,
)
from app.services.recommendations import (
    build_recommendation_status,
    derive_recommendation_budget_context,
    evaluate_flight_option,
    rank_flights,
)
from app.services.recommendations.base import FlightProvider

logger = get_logger(__name__)

MAX_FLIGHT_RECOMMENDATIONS = 5


async def enrich_flight_recommendations(
    trip_plan: TripPlan,
    provider: FlightProvider,
) -> TripPlan:
    """Search, budget-filter, and rank flights without changing other domains."""

    request = build_flight_search_request(trip_plan)
    if request is None:
        return update_flight_recommendations(
            trip_plan,
            flights=[],
            status=build_recommendation_status(searched=False),
        )

    provider_options = await provider.search_flights(request)
    if not provider_options:
        return update_flight_recommendations(
            trip_plan,
            flights=[],
            status=build_recommendation_status(provider_result_count=0),
        )

    context = derive_recommendation_budget_context(trip_plan)
    evaluated_options = [
        option.model_copy(
            update={"budget_evaluation": evaluate_flight_option(context, option)}
        )
        for option in provider_options
    ]

    if context.user_budget_usd is None:
        recommendable = rank_flights(evaluated_options)
        status = build_recommendation_status(
            provider_result_count=len(provider_options),
            affordable_result_count=len(provider_options),
        )
    else:
        recommendable = rank_flights(
            [
                option
                for option in evaluated_options
                if option.budget_evaluation is not None
                and option.budget_evaluation.status == "within_budget"
            ]
        )
        has_unverified_budget = any(
            option.budget_evaluation is not None
            and option.budget_evaluation.status == "unknown"
            for option in evaluated_options
        )
        status = build_recommendation_status(
            provider_result_count=len(provider_options),
            affordable_result_count=len(recommendable),
            budget_verified=not has_unverified_budget,
        )

    selected = recommendable[:MAX_FLIGHT_RECOMMENDATIONS]
    logger.info(
        "flight_recommendations_evaluated provider_count=%s affordable_count=%s selected_count=%s status=%s",
        len(provider_options),
        len(recommendable),
        len(selected),
        status.status,
    )
    return update_flight_recommendations(
        trip_plan,
        flights=selected,
        status=status,
    )


def build_flight_search_request(trip_plan: TripPlan) -> FlightSearchRequest | None:
    """Build an adults-only round trip from authoritative itinerary endpoints."""

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
    outbound_destination = first_day.city.strip() or trip_plan.destination
    return_origin = last_day.city.strip() or trip_plan.destination
    return FlightSearchRequest(
        origin=trip_plan.origin,
        destination=outbound_destination,
        return_origin=return_origin,
        return_destination=trip_plan.origin,
        origin_country_hint=_explicit_country_code(trip_plan.origin),
        destination_country_hint=_day_country_code(first_day),
        return_origin_country_hint=_day_country_code(last_day),
        return_destination_country_hint=_explicit_country_code(trip_plan.origin),
        departure_date=trip_plan.start_date,
        return_date=trip_plan.end_date,
        adults=trip_plan.travelers,
    )


def mark_flight_recommendations_unavailable(trip_plan: TripPlan) -> TripPlan:
    """Record an optional provider outage while retaining every other result."""

    status = (
        build_recommendation_status(provider_available=False)
        if build_flight_search_request(trip_plan) is not None
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
