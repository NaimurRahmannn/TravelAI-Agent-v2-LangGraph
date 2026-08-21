from datetime import UTC, datetime

from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    FlightOption,
    FlightSegment,
    FlightSlice,
    HotelOption,
    ItineraryDay,
    ResolvedPlace,
    TravelRecommendations,
    TripPlan,
    build_hotel_stay_key,
)
from app.services.itinerary_renderer import render_itinerary


def test_renderer_outputs_structured_plan_deterministically():
    plan = TripPlan(
        title="Thailand Highlights",
        origin="Dhaka",
        destination="Thailand",
        duration_days=1,
        travelers=2,
        summary="Culture and history in Bangkok.",
        preferences=["culture"],
        days=[
            ItineraryDay(
                day_number=1,
                city="Bangkok",
                activities=[
                    Activity(
                        name="Grand Palace",
                        category="culture",
                        description="Explore the royal complex.",
                    )
                ],
                estimated_daily_cost_usd=80,
            )
        ],
        budget=BudgetBreakdown(
            items=[
                BudgetItem(category="Food", amount_usd=100),
                BudgetItem(category="Activities", amount_usd=80),
            ],
            estimated_total_usd=0,
            user_budget_usd=200,
        ),
        practical_notes=["Carry some Thai baht."],
    )

    rendered = render_itinerary(plan)

    assert rendered.startswith("# Thailand Highlights")
    assert "## Day 1 — Bangkok" in rendered
    assert "**Grand Palace**" in rendered
    assert "**Listed activity costs:** $80" in rendered
    assert "## Base Trip Estimate" in rendered
    assert "Flights and accommodation are not included." in rendered
    assert "- Food: $100" in rendered
    assert "**Base trip estimate:** $180" in rendered
    assert "**Overall target budget (total for 2 travelers):** $200" in rendered
    assert "Budget status" not in rendered
    assert "- Carry some Thai baht." in rendered


def test_renderer_shows_provider_address_without_internal_metadata():
    plan = TripPlan(
        title="Ayutthaya Highlights",
        destination="Thailand",
        duration_days=1,
        travelers=1,
        preferences=[],
        days=[
            ItineraryDay(
                day_number=1,
                city="Ayutthaya",
                activities=[
                    Activity(
                        name="Wat Mahathat",
                        category="history",
                        place=ResolvedPlace(
                            provider="geoapify",
                            provider_place_id="place-secret-id",
                            name="Wat Mahathat",
                            formatted_address="Ayutthaya, Thailand",
                            latitude=14.3569,
                            longitude=100.5683,
                            confidence=0.98,
                            resolution_status="resolved",
                        ),
                        place_resolution_status="resolved",
                    )
                ],
            )
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Activities", amount_usd=10)],
            estimated_total_usd=10,
        ),
        practical_notes=[],
    )

    rendered = render_itinerary(plan)

    assert "Address: Ayutthaya, Thailand" in rendered
    assert "place-secret-id" not in rendered
    assert "0.98" not in rendered


def test_renderer_keeps_unresolved_activity_usable():
    plan = TripPlan(
        title="Thailand Plan",
        destination="Thailand",
        duration_days=1,
        travelers=1,
        preferences=[],
        days=[
            ItineraryDay(
                day_number=1,
                city="Bangkok",
                activities=[
                    Activity(
                        name="Hidden Market",
                        category="shopping",
                        location_hint="Bangkok, Thailand",
                    )
                ],
            )
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Shopping", amount_usd=10)],
            estimated_total_usd=10,
        ),
        practical_notes=[],
    )

    rendered = render_itinerary(plan)

    assert "**Hidden Market**" in rendered
    assert "Location: Bangkok, Thailand" in rendered


def test_renderer_shows_swoop_shopping_total_and_separate_flight_legs():
    outbound_departure = datetime(2026, 9, 10, 9, 30)
    outbound_arrival = datetime(2026, 9, 11, 7, 20)
    return_departure = datetime(2026, 9, 15, 18, 10)
    return_arrival = datetime(2026, 9, 16, 3, 20)

    def flight_slice(origin, destination, departure, arrival, duration, stops):
        return FlightSlice(
            origin_code=origin,
            destination_code=destination,
            departure_at=departure,
            arrival_at=arrival,
            duration_minutes=duration,
            stops=stops,
            segments=[
                FlightSegment(
                    origin_code=origin,
                    destination_code=destination,
                    departure_at=departure,
                    arrival_at=arrival,
                    duration_minutes=duration,
                    airline_code="QR",
                    airline_name="Qatar Airways",
                    flight_number="641",
                )
            ],
        )

    plan = TripPlan(
        title="Japan plan",
        origin="Dhaka",
        destination="Japan",
        duration_days=1,
        travelers=2,
        preferences=[],
        days=[
            ItineraryDay(
                day_number=1,
                city="Tokyo",
                activities=[Activity(name="Temple", category="culture")],
            )
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Local costs", amount_usd=800)],
            estimated_total_usd=800,
            user_budget_usd=2000,
        ),
        recommendations=TravelRecommendations(
            flights=[
                FlightOption(
                    provider="swoop",
                    provider_offer_id="swoop-renderer",
                    origin_code="DAC",
                    destination_code="HND",
                    adults=2,
                    total_duration_minutes=1870,
                    stops=1,
                    total_price=714.20,
                    currency="USD",
                    price_type="shopping_total",
                    airline_names=["Qatar Airways"],
                    slices=[
                        flight_slice(
                            "DAC",
                            "HND",
                            outbound_departure,
                            outbound_arrival,
                            1010,
                            1,
                        ),
                        flight_slice(
                            "HND",
                            "DAC",
                            return_departure,
                            return_arrival,
                            860,
                            0,
                        ),
                    ],
                    fetched_at=datetime(2026, 8, 20, tzinfo=UTC),
                )
            ],
            flight_status={
                "status": "available",
                "provider_result_count": 1,
            },
        ),
        practical_notes=[],
    )

    rendered = render_itinerary(plan)

    assert "**Flight recommendation: Qatar Airways**" in rendered
    assert "Outbound: DAC → HND" in rendered
    assert "Return: HND → DAC" in rendered
    assert "Total for 2 adults: $714.20" in rendered
    assert "Projected trip total" not in rendered
    assert "trip budget" not in rendered
    assert "Google Flights via Swoop" in rendered


def test_renderer_groups_hotel_rate_as_recommendation_outside_base_estimate():
    plan = TripPlan(
        title="Tokyo plan",
        destination="Japan",
        start_date=datetime(2026, 9, 10).date(),
        end_date=datetime(2026, 9, 13).date(),
        duration_days=3,
        travelers=2,
        preferences=[],
        days=[
            ItineraryDay(
                day_number=1,
                city="Tokyo",
                activities=[Activity(name="Temple", category="culture")],
            )
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Local costs", amount_usd=800)],
            estimated_total_usd=800,
        ),
        recommendations=TravelRecommendations(
            hotels=[
                HotelOption(
                    provider="liteapi",
                    provider_hotel_id="hotel-1",
                    provider_offer_id="offer-1",
                    stay_key=build_hotel_stay_key(
                        "Tokyo",
                        datetime(2026, 9, 10).date(),
                        datetime(2026, 9, 13).date(),
                    ),
                    name="Hotel Sakura",
                    city="Tokyo",
                    check_in=datetime(2026, 9, 10).date(),
                    check_out=datetime(2026, 9, 13).date(),
                    nights=3,
                    total_price=480,
                    currency="USD",
                    price_per_night=160,
                    room_name="Deluxe Room",
                    board_name="Breakfast Included",
                    refundable=True,
                    taxes_included=True,
                    is_sandbox=True,
                    fetched_at=datetime(2026, 8, 21, tzinfo=UTC),
                )
            ],
            hotel_status={"status": "available", "provider_result_count": 1},
        ),
        practical_notes=[],
    )

    rendered = render_itinerary(plan)

    assert "## Hotel Recommendations" in rendered
    assert "### Hotels in Tokyo" in rendered
    assert "Hotel recommendation: Hotel Sakura" in rendered
    assert "Sandbox hotel data" in rendered
    assert "Total stay: $480" in rendered
    assert "Per night: $160" in rendered
    assert "**Base trip estimate:** $800" in rendered
    assert "Projected trip total" not in rendered
