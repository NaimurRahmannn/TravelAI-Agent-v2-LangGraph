from datetime import UTC, date, datetime

from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    FlightOption,
    HotelOption,
    ItineraryDay,
    RecommendationBudgetContext,
    TripPlan,
)
from app.services.recommendations import (
    build_recommendation_status,
    derive_recommendation_budget_context,
    evaluate_flight_hotel_combination,
    evaluate_flight_option,
    evaluate_hotel_option,
    filter_affordable_flights,
    filter_affordable_hotels,
    rank_flights,
    rank_hotels,
)

FETCHED_AT = datetime(2026, 8, 20, 8, tzinfo=UTC)


def _plan(
    *,
    flight_estimate: float = 600,
    hotel_estimate: float = 400,
    other_estimate: float = 400,
    user_budget: float | None = 1500,
) -> TripPlan:
    return TripPlan(
        title="Budget plan",
        origin="Dhaka",
        destination="Thailand",
        duration_days=1,
        travelers=2,
        preferences=[],
        days=[
            ItineraryDay(
                day_number=1,
                city="Bangkok",
                activities=[Activity(name="Grand Palace", category="culture")],
            )
        ],
        budget=BudgetBreakdown(
            items=[
                BudgetItem(
                    category="International Transportation",
                    amount_usd=flight_estimate,
                ),
                BudgetItem(category="Accommodation", amount_usd=hotel_estimate),
                BudgetItem(category="Food and local costs", amount_usd=other_estimate),
            ],
            estimated_total_usd=0,
            user_budget_usd=user_budget,
        ),
        practical_notes=[],
    )


def _flight(
    offer_id: str = "flight-1",
    *,
    price: float = 550,
    currency: str = "USD",
    duration: int = 240,
    stops: int = 0,
) -> FlightOption:
    return FlightOption(
        provider="future-flight-provider",
        provider_offer_id=offer_id,
        origin_code="DAC",
        destination_code="BKK",
        departure_at=datetime(2026, 9, 10, 2, tzinfo=UTC),
        arrival_at=datetime(2026, 9, 10, 8, tzinfo=UTC),
        total_duration_minutes=duration,
        stops=stops,
        total_price=price,
        currency=currency,
        fetched_at=FETCHED_AT,
    )


def _hotel(
    hotel_id: str = "hotel-1",
    *,
    price: float = 350,
    currency: str = "USD",
    rating: float | None = 4.5,
) -> HotelOption:
    return HotelOption(
        provider="future-hotel-provider",
        provider_hotel_id=hotel_id,
        name=f"Hotel {hotel_id}",
        check_in=date(2026, 9, 10),
        check_out=date(2026, 9, 14),
        nights=4,
        total_price=price,
        currency=currency,
        rating=rating,
        fetched_at=FETCHED_AT,
    )


def test_budget_context_derives_flight_hotel_other_and_user_budget():
    context = derive_recommendation_budget_context(_plan())

    assert context.user_budget_usd == 1500
    assert context.estimated_flight_usd == 600
    assert context.estimated_hotel_usd == 400
    assert context.estimated_other_trip_cost_usd == 400


def test_real_flight_and_hotel_replace_estimates_without_double_counting():
    context = derive_recommendation_budget_context(_plan())

    flight_result = evaluate_flight_option(context, _flight(price=550))
    hotel_result = evaluate_hotel_option(context, _hotel(price=350))

    assert flight_result.projected_trip_total_usd == 1350
    assert hotel_result.projected_trip_total_usd == 1350
    assert flight_result.status == "within_budget"
    assert hotel_result.status == "within_budget"


def test_individual_flight_and_hotel_over_total_budget_are_rejected():
    context = derive_recommendation_budget_context(_plan())

    assert evaluate_flight_option(context, _flight(price=800)).status == "over_budget"
    assert evaluate_hotel_option(context, _hotel(price=600)).status == "over_budget"


def test_combination_is_authoritative_when_individual_options_fit():
    context = derive_recommendation_budget_context(
        _plan(
            flight_estimate=300,
            hotel_estimate=300,
            other_estimate=850,
            user_budget=2000,
        )
    )
    flight = _flight(price=680)
    hotel = _hotel(price=590)

    assert evaluate_flight_option(context, flight).status == "within_budget"
    assert evaluate_hotel_option(context, hotel).status == "within_budget"
    combined = evaluate_flight_hotel_combination(context, flight, hotel)

    assert combined.status == "over_budget"
    assert combined.projected_trip_total_usd == 2120
    assert combined.remaining_budget_usd == -120


def test_missing_user_budget_is_unknown_without_rejecting_options():
    context = derive_recommendation_budget_context(_plan(user_budget=None))
    options = [_flight("expensive", price=5000)]

    evaluation = evaluate_flight_option(context, options[0])

    assert evaluation.status == "unknown"
    assert evaluation.reason == "missing_user_budget"
    assert filter_affordable_flights(options, context) == options


def test_non_usd_provider_price_is_unknown_and_not_compared():
    context = derive_recommendation_budget_context(_plan())
    flight = _flight(currency="EUR")

    evaluation = evaluate_flight_option(context, flight)

    assert evaluation.status == "unknown"
    assert evaluation.reason == "currency_mismatch"
    assert evaluation.projected_trip_total_usd is None
    assert filter_affordable_flights([flight], context) == []


def test_affordable_filters_do_not_mutate_provider_results():
    context = derive_recommendation_budget_context(_plan())
    flights = [_flight("over", price=900), _flight("fits", price=500)]
    hotels = [_hotel("over", price=700), _hotel("fits", price=300)]

    affordable_flights = filter_affordable_flights(flights, context)
    affordable_hotels = filter_affordable_hotels(hotels, context)

    assert [option.provider_offer_id for option in affordable_flights] == ["fits"]
    assert [option.provider_hotel_id for option in affordable_hotels] == ["fits"]
    assert len(flights) == 2
    assert len(hotels) == 2


def test_ranking_is_deterministic_with_stable_tie_breakers():
    flights = [
        _flight("b", price=500, duration=200, stops=1),
        _flight("c", price=450, duration=300, stops=0),
        _flight("a", price=500, duration=200, stops=1),
    ]
    hotels = [
        _hotel("b", price=300, rating=4.5),
        _hotel("c", price=250, rating=3.0),
        _hotel("a", price=300, rating=4.5),
        _hotel("unrated", price=300, rating=None),
    ]

    assert [item.provider_offer_id for item in rank_flights(flights)] == [
        "c",
        "a",
        "b",
    ]
    assert [item.provider_hotel_id for item in rank_hotels(hotels)] == [
        "c",
        "a",
        "b",
        "unrated",
    ]


def test_status_distinguishes_no_results_from_no_affordable_results():
    no_results = build_recommendation_status(
        provider_result_count=0,
        affordable_result_count=0,
    )
    none_affordable = build_recommendation_status(
        provider_result_count=20,
        affordable_result_count=0,
    )
    available = build_recommendation_status(
        provider_result_count=20,
        affordable_result_count=3,
    )

    assert no_results.status == "no_results"
    assert none_affordable.status == "no_affordable_results"
    assert none_affordable.provider_result_count == 20
    assert available.status == "available"
    assert available.affordable_result_count == 3


def test_context_model_rejects_negative_costs():
    context_data = {
        "estimated_flight_usd": 100,
        "estimated_hotel_usd": 100,
        "estimated_other_trip_cost_usd": -1,
    }

    try:
        RecommendationBudgetContext.model_validate(context_data)
    except ValueError:
        pass
    else:
        raise AssertionError("Negative recommendation budget costs must be rejected")
