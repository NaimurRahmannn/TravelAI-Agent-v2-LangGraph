import asyncio
from datetime import UTC, date, datetime, timedelta

from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    FlightOption,
    FlightSegment,
    FlightSlice,
    HotelOption,
    ItineraryDay,
    RecommendationDomainState,
    ResolvedPlace,
    TravelRecommendations,
    TripPlan,
)
from app.services.flight_recommendation import (
    MAX_FLIGHT_RECOMMENDATIONS,
    build_flight_search_request,
    enrich_flight_recommendations,
)

FETCHED_AT = datetime(2026, 8, 20, 8, tzinfo=UTC)


def _day(day_number: int, city: str, country_code: str) -> ItineraryDay:
    place = ResolvedPlace(
        provider="geoapify",
        provider_place_id=f"place-{day_number}",
        name=city,
        country_code=country_code,
        latitude=35 + day_number,
        longitude=139,
        resolution_status="resolved",
    )
    return ItineraryDay(
        day_number=day_number,
        date=date(2026, 9, 9) + timedelta(days=day_number),
        city=city,
        activities=[
            Activity(
                name=f"Activity {day_number}",
                category="culture",
                place=place,
                place_resolution_status="resolved",
            )
        ],
    )


def _plan(*, user_budget: float | None = 2000) -> TripPlan:
    return TripPlan(
        title="Japan plan",
        origin="Dhaka",
        destination="Japan",
        start_date=date(2026, 9, 10),
        end_date=date(2026, 9, 15),
        duration_days=6,
        travelers=2,
        preferences=[],
        days=[_day(1, "Tokyo", "JP"), _day(6, "Osaka", "JP")],
        budget=BudgetBreakdown(
            items=[
                BudgetItem(category="Food and activities", amount_usd=500),
            ],
            estimated_total_usd=0,
            user_budget_usd=user_budget,
        ),
        practical_notes=[],
    )


def _flight(
    offer_id: str,
    price: float,
    *,
    currency: str = "USD",
    duration: int = 600,
    stops: int = 0,
) -> FlightOption:
    departure = datetime(2026, 9, 10, 2)
    arrival = departure + timedelta(minutes=duration)
    return FlightOption(
        provider="swoop",
        provider_offer_id=offer_id,
        origin_code="DAC",
        destination_code="HND",
        adults=2,
        total_duration_minutes=duration,
        stops=stops,
        total_price=price,
        currency=currency,
        price_type="shopping_total",
        airline_names=["Example Airways"],
        slices=[
            FlightSlice(
                origin_code="DAC",
                destination_code="HND",
                departure_at=departure,
                arrival_at=arrival,
                duration_minutes=duration,
                stops=stops,
                segments=[
                    FlightSegment(
                        origin_code="DAC",
                        destination_code="HND",
                        departure_at=departure,
                        arrival_at=arrival,
                        duration_minutes=duration,
                        airline_name="Example Airways",
                    )
                ],
            )
        ],
        fetched_at=FETCHED_AT,
    )


class Provider:
    def __init__(self, options: list[FlightOption]) -> None:
        self.options = options
        self.requests = []

    async def search_flights(self, request):
        self.requests.append(request)
        return self.options


def test_search_request_uses_first_last_cities_selected_dates_and_adults():
    request = build_flight_search_request(_plan())

    assert request is not None
    assert request.origin == "Dhaka"
    assert request.destination == "Tokyo"
    assert request.return_origin == "Osaka"
    assert request.return_destination == "Dhaka"
    assert request.destination_country_hint == "JP"
    assert request.return_origin_country_hint == "JP"
    assert request.departure_date == date(2026, 9, 10)
    assert request.return_date == date(2026, 9, 15)
    assert request.adults == 2


def test_results_are_ranked_and_available_regardless_of_user_budget():
    provider = Provider(
        [
            _flight("middle", 800),
            _flight("over-target", 1200),
            _flight("lowest", 500),
        ]
    )

    enriched = asyncio.run(
        enrich_flight_recommendations(_plan(user_budget=1000), provider)
    )

    assert [item.provider_offer_id for item in enriched.recommendations.flights] == [
        "lowest",
        "middle",
        "over-target",
    ]
    assert "budget_evaluation" not in enriched.recommendations.flights[0].model_dump()
    assert enriched.recommendations.flight_status.status == "available"
    assert enriched.recommendations.flight_status.provider_result_count == 3


def test_expensive_options_still_have_available_status():
    provider = Provider([_flight("expensive-1", 9001), _flight("expensive-2", 10000)])

    enriched = asyncio.run(enrich_flight_recommendations(_plan(), provider))

    assert [item.provider_offer_id for item in enriched.recommendations.flights] == [
        "expensive-1",
        "expensive-2",
    ]
    assert enriched.recommendations.flight_status.status == "available"


def test_non_usd_result_remains_available_without_budget_comparison():
    provider = Provider([_flight("eur", 500, currency="EUR")])

    enriched = asyncio.run(enrich_flight_recommendations(_plan(), provider))

    assert [item.provider_offer_id for item in enriched.recommendations.flights] == [
        "eur"
    ]
    assert enriched.recommendations.flight_status.status == "available"


def test_empty_provider_result_has_no_results_status():
    enriched = asyncio.run(enrich_flight_recommendations(_plan(), Provider([])))

    assert enriched.recommendations.flights == []
    assert enriched.recommendations.flight_status.status == "no_results"


def test_no_budget_retains_deterministically_ranked_top_five():
    options = [
        _flight(f"offer-{index}", 500 - index, duration=700 - index)
        for index in range(8)
    ]

    enriched = asyncio.run(
        enrich_flight_recommendations(_plan(user_budget=None), Provider(options))
    )

    assert len(enriched.recommendations.flights) == MAX_FLIGHT_RECOMMENDATIONS
    assert [item.provider_offer_id for item in enriched.recommendations.flights] == [
        "offer-7",
        "offer-6",
        "offer-5",
        "offer-4",
        "offer-3",
    ]


def test_flight_update_preserves_existing_hotel_and_restaurant_state():
    plan = _plan()
    hotel = HotelOption(
        provider="future-hotel",
        provider_hotel_id="hotel-1",
        name="Hotel",
        check_in=date(2026, 9, 10),
        check_out=date(2026, 9, 15),
        nights=5,
        total_price=400,
        currency="USD",
        fetched_at=FETCHED_AT,
    )
    plan.recommendations = TravelRecommendations(
        hotels=[hotel],
        hotel_status=RecommendationDomainState(
            status="available",
            provider_result_count=1,
        ),
    )

    enriched = asyncio.run(
        enrich_flight_recommendations(plan, Provider([_flight("fits", 700)]))
    )

    assert enriched.recommendations.hotels == [hotel]
    assert enriched.recommendations.hotel_status.status == "available"
    assert enriched.recommendations.restaurant_status.status == "not_searched"


def test_ineligible_plan_is_not_searched_and_provider_is_not_called():
    plan = _plan()
    plan.start_date = None
    provider = Provider([_flight("unused", 500)])

    enriched = asyncio.run(enrich_flight_recommendations(plan, provider))

    assert provider.requests == []
    assert enriched.recommendations.flight_status.status == "not_searched"
