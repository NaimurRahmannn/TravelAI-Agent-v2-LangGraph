from datetime import UTC, date, datetime

from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    FlightOption,
    FlightSegment,
    FlightSlice,
    HotelOption,
    ItineraryDay,
    SelectedHotelStay,
    TravelRecommendations,
    TravelSelections,
    TripPlan,
    build_hotel_stay_key,
)
from app.services.itinerary_renderer import render_itinerary
from app.services.selection_status import build_travel_selection_status


def _selectable_plan() -> TripPlan:
    start = date(2026, 9, 10)
    end = date(2026, 9, 12)
    departure = datetime(2026, 9, 10, 1, tzinfo=UTC)
    arrival = datetime(2026, 9, 10, 5, tzinfo=UTC)
    segment = FlightSegment(
        origin_code="DAC",
        destination_code="HND",
        departure_at=departure,
        arrival_at=arrival,
        duration_minutes=240,
        airline_name="Test Air",
    )
    flight_slice = FlightSlice(
        origin_code="DAC",
        destination_code="HND",
        departure_at=departure,
        arrival_at=arrival,
        duration_minutes=240,
        stops=0,
        segments=[segment],
    )
    stay_key = build_hotel_stay_key("Tokyo", start, end)
    return TripPlan(
        title="Mountain Japan",
        origin="Dhaka",
        destination="Japan",
        start_date=start,
        end_date=end,
        duration_days=2,
        travelers=1,
        preferences=["mountains", "temples"],
        days=[
            ItineraryDay(
                day_number=day_number,
                date=start if day_number == 1 else date(2026, 9, 11),
                city="Tokyo",
                activities=[
                    Activity(
                        name=f"Mountain activity {day_number}",
                        category="nature",
                        preference_tags=["mountains"],
                    )
                ],
            )
            for day_number in (1, 2)
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Local costs", amount_usd=200)],
            estimated_total_usd=200,
        ),
        recommendations=TravelRecommendations(
            flights=[
                FlightOption(
                    provider="swoop",
                    provider_offer_id="flight-1",
                    origin_code="DAC",
                    destination_code="HND",
                    adults=1,
                    total_duration_minutes=240,
                    stops=0,
                    total_price=500,
                    currency="USD",
                    price_type="shopping_total",
                    airline_names=["Test Air"],
                    slices=[flight_slice],
                    fetched_at=datetime(2026, 8, 25, tzinfo=UTC),
                )
            ],
            hotels=[
                HotelOption(
                    provider="liteapi",
                    provider_hotel_id="hotel-1",
                    provider_offer_id="hotel-offer-1",
                    stay_key=stay_key,
                    name="Mountain View Hotel",
                    city="Tokyo",
                    check_in=start,
                    check_out=end,
                    nights=2,
                    total_price=300,
                    currency="USD",
                    fetched_at=datetime(2026, 8, 25, tzinfo=UTC),
                )
            ],
            flight_status={"status": "available", "provider_result_count": 1},
            hotel_status={"status": "available", "provider_result_count": 1},
        ),
        practical_notes=[],
    )


def test_fresh_recommendations_require_new_flight_and_hotel_selections():
    plan = _selectable_plan()

    status = build_travel_selection_status(plan, None)

    assert status.flight == "required"
    assert status.hotel == "required"


def test_confirmed_snapshot_reports_both_selections_as_selected():
    plan = _selectable_plan()
    hotel = plan.recommendations.hotels[0]
    selections = TravelSelections(
        selected_flight_id="flight-1",
        selected_hotels=[
            SelectedHotelStay(
                stay_key=hotel.stay_key,
                hotel_option_id=hotel.provider_offer_id,
            )
        ],
    )

    status = build_travel_selection_status(plan, selections)

    assert status.flight == "selected"
    assert status.hotel == "selected"


def test_partial_split_flight_candidates_cannot_be_confirmed_as_a_round_trip():
    plan = _selectable_plan()
    recommendations = plan.recommendations
    assert recommendations is not None
    recommendations.return_flights = list(recommendations.flights)
    recommendations.return_flight_status = {
        "status": "available",
        "provider_result_count": 1,
    }
    recommendations.outbound_flights = []
    recommendations.outbound_flight_status = {
        "status": "no_results",
        "provider_result_count": 0,
    }

    status = build_travel_selection_status(plan, None)

    assert status.flight == "unavailable"


def test_renderer_asks_for_selection_only_for_fresh_complete_options():
    plan = _selectable_plan()

    rendered = render_itinerary(plan)

    assert "## Select Your Travel Options" in rendered
    assert "select one flight and one hotel for each stay" in rendered
    assert "No booking will be made" in rendered
