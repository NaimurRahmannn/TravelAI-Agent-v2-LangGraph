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
    build_hotel_stay_key,
)
from app.services.hotel_recommendation import (
    derive_hotel_stays,
    enrich_hotel_recommendations,
)

FETCHED_AT = datetime(2026, 8, 21, tzinfo=UTC)


def _day(number: int, city: str, day_date: date) -> ItineraryDay:
    return ItineraryDay(
        day_number=number,
        date=day_date,
        city=city,
        activities=[
            Activity(
                name=f"Museum {number}",
                category="culture",
                place=ResolvedPlace(
                    provider="geoapify",
                    provider_place_id=f"place-{number}",
                    name=f"Museum {number}",
                    city=city,
                    latitude=35 + number / 100,
                    longitude=139 + number / 100,
                    resolution_status="resolved",
                ),
                place_resolution_status="resolved",
            )
        ],
    )


def _plan(cities: list[str], *, end_date: date | None = None) -> TripPlan:
    start = date(2026, 8, 21)
    days = [
        _day(index, city, start + timedelta(days=index - 1))
        for index, city in enumerate(cities, 1)
    ]
    return TripPlan(
        title="Japan plan",
        origin="Dhaka",
        destination="Japan",
        start_date=start,
        end_date=end_date or start + timedelta(days=len(cities)),
        duration_days=len(cities),
        travelers=2,
        guest_nationality_country_code="BD",
        preferences=[],
        days=days,
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Local costs", amount_usd=800)],
            estimated_total_usd=800,
            user_budget_usd=1000,
        ),
        practical_notes=[],
    )


def _hotel(request, hotel_id: str, price: float, rating: float = 4.0) -> HotelOption:
    return HotelOption(
        provider="liteapi",
        provider_hotel_id=hotel_id,
        provider_offer_id=f"offer-{hotel_id}",
        stay_key=build_hotel_stay_key(
            request.city,
            request.check_in,
            request.check_out,
        ),
        name=f"Hotel {hotel_id}",
        city=request.city,
        check_in=request.check_in,
        check_out=request.check_out,
        nights=(request.check_out - request.check_in).days,
        total_price=price,
        currency="USD",
        rating=rating,
        fetched_at=FETCHED_AT,
    )


class Provider:
    def __init__(self, results=None, failures=()):
        self.results = results or {}
        self.failures = set(failures)
        self.requests = []

    async def search_hotels(self, request):
        self.requests.append(request)
        if request.city in self.failures:
            raise RuntimeError("provider unavailable")
        prices = self.results.get(request.city, [])
        return [
            _hotel(request, f"{request.city}-{index}", price, 5 - index / 10)
            for index, price in enumerate(prices)
        ]


def _flight() -> FlightOption:
    departure = datetime(2026, 8, 21, 3)
    arrival = datetime(2026, 8, 21, 9)
    segment = FlightSegment(
        origin_code="DAC",
        destination_code="NRT",
        departure_at=departure,
        arrival_at=arrival,
        duration_minutes=360,
        airline_name="Example Air",
    )
    return FlightOption(
        provider="swoop",
        provider_offer_id="flight-1",
        origin_code="DAC",
        destination_code="NRT",
        adults=2,
        total_duration_minutes=360,
        stops=0,
        total_price=900,
        currency="USD",
        price_type="shopping_total",
        airline_names=["Example Air"],
        slices=[
            FlightSlice(
                origin_code="DAC",
                destination_code="NRT",
                departure_at=departure,
                arrival_at=arrival,
                duration_minutes=360,
                stops=0,
                segments=[segment],
            )
        ],
        fetched_at=FETCHED_AT,
    )


def test_single_city_stay_uses_checkout_exclusive_night_count():
    stays = derive_hotel_stays(_plan(["Tokyo", "Tokyo", "Tokyo"]))

    assert [
        (stay.city, stay.check_in, stay.check_out, stay.nights)
        for stay in stays
    ] == [("Tokyo", date(2026, 8, 21), date(2026, 8, 24), 3)]


def test_multi_city_and_repeated_city_stays_have_separate_windows():
    plan = _plan(
        ["Tokyo", "Tokyo", "Tokyo", "Kyoto", "Kyoto", "Osaka", "Osaka"],
        end_date=date(2026, 8, 27),
    )
    stays = derive_hotel_stays(plan)

    assert [(stay.city, stay.check_in, stay.check_out) for stay in stays] == [
        ("Tokyo", date(2026, 8, 21), date(2026, 8, 24)),
        ("Kyoto", date(2026, 8, 24), date(2026, 8, 26)),
        ("Osaka", date(2026, 8, 26), date(2026, 8, 27)),
    ]

    repeated = derive_hotel_stays(_plan(["Tokyo", "Kyoto", "Tokyo"]))
    assert [stay.city for stay in repeated] == ["Tokyo", "Kyoto", "Tokyo"]


def test_zero_night_segment_is_not_searched():
    plan = _plan(["Tokyo"], end_date=date(2026, 8, 21))
    provider = Provider({"Tokyo": [400]})

    assert derive_hotel_stays(plan) == []
    enriched = asyncio.run(enrich_hotel_recommendations(plan, provider))
    assert provider.requests == []
    assert enriched.recommendations.hotel_status.status == "not_searched"


def test_hotels_ignore_user_budget_and_leave_base_budget_and_flights_unchanged():
    plan = _plan(["Tokyo"])
    flight = _flight()
    plan.recommendations = TravelRecommendations(
        flights=[flight],
        flight_status=RecommendationDomainState(
            status="available", provider_result_count=1
        ),
    )
    provider = Provider({"Tokyo": [700, 1200, 400]})

    enriched = asyncio.run(enrich_hotel_recommendations(plan, provider))

    assert [hotel.total_price for hotel in enriched.recommendations.hotels] == [
        400,
        700,
        1200,
    ]
    assert enriched.budget.estimated_total_usd == 800
    assert [item.category for item in enriched.budget.items] == ["Local costs"]
    assert enriched.recommendations.flights == [flight]
    assert enriched.recommendations.flight_status.status == "available"
    assert provider.requests[0].latitude == 35.01
    assert provider.requests[0].longitude == 139.01
    assert provider.requests[0].adults == 2
    assert provider.requests[0].guest_nationality_country_code == "BD"
    assert provider.requests[0].radius_meters == 5_000


def test_partial_multi_city_failure_preserves_successful_results():
    plan = _plan(["Tokyo", "Kyoto", "Osaka"])
    provider = Provider(
        {"Tokyo": [500], "Osaka": [450]},
        failures={"Kyoto"},
    )

    enriched = asyncio.run(enrich_hotel_recommendations(plan, provider))

    assert [hotel.city for hotel in enriched.recommendations.hotels] == [
        "Tokyo",
        "Osaka",
    ]
    assert enriched.recommendations.hotel_status.status == "available"


def test_empty_success_is_no_results_and_all_failures_are_unavailable():
    plan = _plan(["Tokyo"])

    empty = asyncio.run(enrich_hotel_recommendations(plan, Provider()))
    failed = asyncio.run(
        enrich_hotel_recommendations(plan, Provider(failures={"Tokyo"}))
    )

    assert empty.recommendations.hotel_status.status == "no_results"
    assert failed.recommendations.hotel_status.status == "unavailable"


def test_missing_nationality_never_calls_provider_or_uses_origin_as_fallback():
    plan = _plan(["Tokyo"])
    plan.guest_nationality_country_code = None
    provider = Provider({"Tokyo": [400]})

    enriched = asyncio.run(enrich_hotel_recommendations(plan, provider))

    assert provider.requests == []
    assert enriched.recommendations.hotel_status.status == "unavailable"


def test_zero_zero_coordinates_are_not_used_as_search_anchor():
    plan = _plan(["Tokyo"])
    activity = plan.days[0].activities[0]
    activity.place.latitude = 0
    activity.place.longitude = 0
    provider = Provider({"Tokyo": [400]})

    enriched = asyncio.run(enrich_hotel_recommendations(plan, provider))

    assert provider.requests == []
    assert enriched.recommendations.hotel_status.status == "unavailable"
