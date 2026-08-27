import asyncio
from datetime import date

from app.graph.nodes import hotel_recommendation, trip_extension
from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    ConfirmedTripSnapshot,
    ItineraryDay,
    RecommendationDomainState,
    TravelRecommendations,
    TravelSelections,
    Trip,
    TripCostSummary,
    TripPlan,
)
from app.services.hotel_recommendation import derive_hotel_stays


def _plan(*, duration: int = 3) -> TripPlan:
    start = date(2026, 9, 10)
    return TripPlan(
        title="Japan plan",
        origin="Dhaka",
        destination="Japan",
        start_date=start,
        end_date=date(2026, 9, 9 + duration),
        duration_days=duration,
        travelers=2,
        preferences=[],
        days=[
            ItineraryDay(
                day_number=number,
                date=date(2026, 9, 9 + number),
                city="Tokyo",
                activities=[
                    Activity(name=f"Activity {number}", category="visit")
                ],
            )
            for number in range(1, duration + 1)
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Local costs", amount_usd=100 * duration)],
            estimated_total_usd=100 * duration,
        ),
        recommendations=TravelRecommendations(
            flight_status=RecommendationDomainState(),
            hotel_status=RecommendationDomainState(),
        ),
        practical_notes=[],
    )


def test_extension_updates_dates_and_merge_preserves_existing_days():
    base = _plan(duration=3)
    trip = Trip(
        origin="Dhaka",
        destination="Japan",
        start_date=base.start_date,
        end_date=base.end_date,
        duration=base.duration_days,
        travelers=base.travelers,
    )
    mutation = trip_extension.trip_extension_node(
        {
            "trip": trip,
            "itinerary": base,
            "extension_days": 2,
        },
        config={},
    )

    assert mutation["trip"].end_date == date(2026, 9, 14)
    assert mutation["trip"].duration == 5
    generated = _plan(duration=5)
    generated.days[0].activities[0].name = "Model rewrote old day"
    merged = trip_extension.extension_merge_node(
        {
            **mutation,
            "itinerary": generated,
        },
        config={},
    )["itinerary"]

    assert merged.days[:3] == base.days
    assert [day.day_number for day in merged.days] == [1, 2, 3, 4, 5]
    assert merged.end_date == date(2026, 9, 14)


def test_failed_extension_generation_restores_original_trip_and_itinerary():
    base = _plan(duration=3)
    trip = Trip(
        origin="Dhaka",
        destination="Japan",
        start_date=base.start_date,
        end_date=base.end_date,
        duration=base.duration_days,
        travelers=base.travelers,
    )
    mutation = trip_extension.trip_extension_node(
        {"trip": trip, "itinerary": base, "extension_days": 2},
        config={},
    )

    result = trip_extension.extension_merge_node(
        {**mutation, "itinerary": None},
        config={},
    )

    assert result["extension_ready"] is False
    assert result["trip"] == trip
    assert result["itinerary"] == base


def test_extension_marks_confirmed_snapshot_stale_and_failure_restores_it():
    base = _plan(duration=3)
    trip = Trip(
        origin="Dhaka",
        destination="Japan",
        start_date=base.start_date,
        end_date=base.end_date,
        duration=base.duration_days,
        travelers=base.travelers,
    )
    confirmed = ConfirmedTripSnapshot(
        revision=3,
        itinerary=base,
        selections=TravelSelections(selected_flight_id="confirmed-flight"),
        cost_summary=TripCostSummary(
            base_trip_total_usd=300,
            selected_flight_usd=700,
            selected_hotels_usd=0,
            additions_total_usd=700,
            updated_trip_total_usd=1000,
        ),
    )

    mutation = trip_extension.trip_extension_node(
        {
            "trip": trip,
            "itinerary": base,
            "extension_days": 2,
            "confirmed_snapshot": confirmed,
        },
        config={},
    )

    assert mutation["confirmed_snapshot"].status == "stale"
    assert mutation["confirmed_snapshot"].cost_summary == confirmed.cost_summary
    assert mutation["extension_base_confirmed_snapshot"] == confirmed

    failed = trip_extension.extension_merge_node(
        {**mutation, "itinerary": None},
        config={},
    )
    assert failed["confirmed_snapshot"] == confirmed


def test_extension_hotel_scope_starts_at_previous_end_date(monkeypatch):
    plan = _plan(duration=5)
    old_end = date(2026, 9, 12)
    captured = {}

    async def fake_enrich(scoped, provider, *, anchor_provider=None):
        captured["stays"] = derive_hotel_stays(scoped)
        return scoped

    monkeypatch.setattr(
        hotel_recommendation,
        "enrich_hotel_recommendations",
        fake_enrich,
    )
    result = asyncio.run(
        hotel_recommendation._enrich_extension_hotels(
            plan,
            old_end,
            provider=object(),
            anchor_provider=None,
        )
    )

    assert result.days == plan.days
    assert len(captured["stays"]) == 1
    assert captured["stays"][0].check_in == old_end
    assert captured["stays"][0].check_out == plan.end_date
