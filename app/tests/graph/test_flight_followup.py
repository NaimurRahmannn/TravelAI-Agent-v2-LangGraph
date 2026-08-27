from datetime import UTC, date, datetime, timedelta

from langchain_core.messages import HumanMessage

from app.graph import builder
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
    TravelRecommendations,
    TripPlan,
    build_hotel_stay_key,
)
from app.services.flight_recommendation import update_flight_recommendations


def _flight() -> FlightOption:
    departure = datetime(2026, 9, 10, 9, 30, tzinfo=UTC)
    arrival = departure + timedelta(hours=8)
    segment = FlightSegment(
        origin_code="DAC",
        destination_code="HND",
        departure_at=departure,
        arrival_at=arrival,
        duration_minutes=480,
        airline_name="Example Airways",
    )
    return FlightOption(
        provider="swoop",
        provider_offer_id="outbound-1",
        origin_code="DAC",
        destination_code="HND",
        adults=2,
        total_duration_minutes=480,
        stops=0,
        total_price=700,
        currency="USD",
        price_type="shopping_total",
        airline_names=["Example Airways"],
        slices=[
            FlightSlice(
                origin_code="DAC",
                destination_code="HND",
                departure_at=departure,
                arrival_at=arrival,
                duration_minutes=480,
                stops=0,
                segments=[segment],
            )
        ],
        fetched_at=datetime(2026, 8, 27, tzinfo=UTC),
    )


def _plan() -> TripPlan:
    check_in = date(2026, 9, 10)
    check_out = date(2026, 9, 15)
    hotel = HotelOption(
        provider="liteapi",
        provider_hotel_id="hotel-1",
        provider_offer_id="hotel-offer-1",
        stay_key=build_hotel_stay_key("Tokyo", check_in, check_out),
        name="Existing Hotel",
        city="Tokyo",
        check_in=check_in,
        check_out=check_out,
        nights=5,
        total_price=500,
        currency="USD",
        fetched_at=datetime(2026, 8, 27, tzinfo=UTC),
    )
    return TripPlan(
        title="Existing Japan plan",
        origin="Dhaka",
        destination="Japan",
        start_date=check_in,
        end_date=check_out,
        duration_days=6,
        travelers=2,
        preferences=[],
        days=[
            ItineraryDay(
                day_number=1,
                city="Tokyo",
                activities=[Activity(name="Existing activity", category="culture")],
            )
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Local costs", amount_usd=500)],
            estimated_total_usd=500,
        ),
        recommendations=TravelRecommendations(
            hotels=[hotel],
            hotel_status=RecommendationDomainState(
                status="available",
                provider_result_count=1,
            ),
        ),
        practical_notes=[],
    )


def test_departure_flight_follow_up_preserves_plan_and_skips_replanning(monkeypatch):
    original = _plan()

    def fail_extractor(state, config):
        raise AssertionError("flight follow-up must not enter trip extraction")

    def add_outbound_flight(state, config):
        assert state["flight_search_scope"] == "outbound"
        return {
            "itinerary": update_flight_recommendations(
                state["itinerary"],
                flights=[_flight()],
                status=RecommendationDomainState(
                    status="available",
                    provider_result_count=1,
                ),
            )
        }

    monkeypatch.setattr(builder, "extractor_node", fail_extractor)
    monkeypatch.setattr(builder, "flight_recommendation_node", add_outbound_flight)
    graph = builder._build_graph()

    result = graph.invoke(
        {
            "messages": [
                HumanMessage(content="Can you suggest me departure flights?")
            ],
            "itinerary": original,
        }
    )

    assert result["itinerary"].title == original.title
    assert result["itinerary"].days == original.days
    assert result["itinerary"].recommendations.hotels == (
        original.recommendations.hotels
    )
    assert result["flight_search_scope"] == "outbound"
    assert result["response"].startswith("## Departure Flight Suggestions")
    assert "Travel date: **2026-09-10**" in result["response"]
    assert "Departs: 2026-09-10 09:30 UTC" in result["response"]
    assert "Existing activity" not in result["response"]
    assert result["messages"][-1].content == result["response"]
