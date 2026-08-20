import re
from typing import Literal

from app.models import (
    BudgetEvaluation,
    FlightOption,
    HotelOption,
    RecommendationBudgetContext,
    RecommendationDomainState,
    TripPlan,
)

RecommendationBudgetCategory = Literal["flight", "hotel", "other"]

_FLIGHT_TERMS = (
    "airfare",
    "air fare",
    "air travel",
    "airline",
    "flight",
    "international transportation",
    "international transport",
)
_HOTEL_TERMS = ("accommodation", "hotel", "lodging")


def derive_recommendation_budget_context(
    trip_plan: TripPlan,
) -> RecommendationBudgetContext:
    """Split the existing USD estimate into replaceable and retained costs."""

    flight_total = 0.0
    hotel_total = 0.0
    other_total = 0.0
    for item in trip_plan.budget.items:
        category = recommendation_budget_category(item.category)
        if category == "flight":
            flight_total += item.amount_usd
        elif category == "hotel":
            hotel_total += item.amount_usd
        else:
            other_total += item.amount_usd
    return RecommendationBudgetContext(
        user_budget_usd=trip_plan.budget.user_budget_usd,
        estimated_flight_usd=_money(flight_total),
        estimated_hotel_usd=_money(hotel_total),
        estimated_other_trip_cost_usd=_money(other_total),
    )


def recommendation_budget_category(category: str) -> RecommendationBudgetCategory:
    """Classify only stable flight/hotel labels; retain everything else."""

    normalized = " ".join(re.sub(r"[^a-z0-9]+", " ", category.casefold()).split())
    if any(term in normalized for term in _HOTEL_TERMS):
        return "hotel"
    if any(term in normalized for term in _FLIGHT_TERMS):
        return "flight"
    return "other"


def evaluate_flight_option(
    context: RecommendationBudgetContext,
    option: FlightOption,
) -> BudgetEvaluation:
    """Replace the itinerary flight estimate with one provider price."""

    return _evaluate_projected_total(
        context,
        flight_price=option.total_price,
        flight_currency=option.currency,
    )


def evaluate_hotel_option(
    context: RecommendationBudgetContext,
    option: HotelOption,
) -> BudgetEvaluation:
    """Replace the itinerary hotel estimate with one provider stay price."""

    return _evaluate_projected_total(
        context,
        hotel_price=option.total_price,
        hotel_currency=option.currency,
    )


def evaluate_flight_hotel_combination(
    context: RecommendationBudgetContext,
    flight: FlightOption,
    hotel: HotelOption,
) -> BudgetEvaluation:
    """Authoritatively evaluate both real prices in one projected total."""

    return _evaluate_projected_total(
        context,
        flight_price=flight.total_price,
        flight_currency=flight.currency,
        hotel_price=hotel.total_price,
        hotel_currency=hotel.currency,
    )


def filter_affordable_flights(
    options: list[FlightOption],
    context: RecommendationBudgetContext,
) -> list[FlightOption]:
    """Keep only authoritative fits, or all options when no budget exists."""

    if context.user_budget_usd is None:
        return rank_flights(options)
    return rank_flights(
        [
            option
            for option in options
            if evaluate_flight_option(context, option).status == "within_budget"
        ]
    )


def filter_affordable_hotels(
    options: list[HotelOption],
    context: RecommendationBudgetContext,
) -> list[HotelOption]:
    """Keep only authoritative fits, or all options when no budget exists."""

    if context.user_budget_usd is None:
        return rank_hotels(options)
    return rank_hotels(
        [
            option
            for option in options
            if evaluate_hotel_option(context, option).status == "within_budget"
        ]
    )


def rank_flights(options: list[FlightOption]) -> list[FlightOption]:
    """Return a stable provider-neutral flight ordering."""

    return sorted(
        options,
        key=lambda option: (
            option.total_price,
            option.total_duration_minutes,
            option.stops,
            option.provider,
            option.provider_offer_id,
        ),
    )


def rank_hotels(options: list[HotelOption]) -> list[HotelOption]:
    """Return a stable provider-neutral hotel ordering."""

    return sorted(
        options,
        key=lambda option: (
            option.total_price,
            option.rating is None,
            -(option.rating or 0),
            option.provider,
            option.provider_hotel_id,
        ),
    )


def build_recommendation_status(
    *,
    provider_result_count: int = 0,
    affordable_result_count: int = 0,
    searched: bool = True,
    provider_available: bool = True,
) -> RecommendationDomainState:
    """Distinguish search, outage, empty, rejected, and successful outcomes."""

    if not searched:
        return RecommendationDomainState(status="not_searched")
    if not provider_available:
        return RecommendationDomainState(status="unavailable")
    if provider_result_count == 0:
        return RecommendationDomainState(status="no_results")
    if affordable_result_count == 0:
        return RecommendationDomainState(
            status="no_affordable_results",
            provider_result_count=provider_result_count,
        )
    return RecommendationDomainState(
        status="available",
        provider_result_count=provider_result_count,
        affordable_result_count=affordable_result_count,
    )


def _evaluate_projected_total(
    context: RecommendationBudgetContext,
    *,
    flight_price: float | None = None,
    flight_currency: str | None = None,
    hotel_price: float | None = None,
    hotel_currency: str | None = None,
) -> BudgetEvaluation:
    currencies = {
        currency
        for currency in (flight_currency, hotel_currency)
        if currency is not None
    }
    if any(currency != "USD" for currency in currencies):
        return BudgetEvaluation(status="unknown", reason="currency_mismatch")

    projected_total = _money(
        context.estimated_other_trip_cost_usd
        + (flight_price if flight_price is not None else context.estimated_flight_usd)
        + (hotel_price if hotel_price is not None else context.estimated_hotel_usd)
    )
    if context.user_budget_usd is None:
        return BudgetEvaluation(
            status="unknown",
            reason="missing_user_budget",
            projected_trip_total_usd=projected_total,
        )

    remaining = _money(context.user_budget_usd - projected_total)
    if projected_total <= context.user_budget_usd:
        return BudgetEvaluation(
            status="within_budget",
            reason="within_total_budget",
            projected_trip_total_usd=projected_total,
            remaining_budget_usd=remaining,
        )
    return BudgetEvaluation(
        status="over_budget",
        reason="exceeds_total_budget",
        projected_trip_total_usd=projected_total,
        remaining_budget_usd=remaining,
    )


def _money(value: float) -> float:
    return round(value, 2)
