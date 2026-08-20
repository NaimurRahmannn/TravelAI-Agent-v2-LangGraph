import asyncio
from datetime import date
from types import SimpleNamespace

from app.graph.nodes import hotel_recommendation
from app.models import Activity, BudgetBreakdown, BudgetItem, ItineraryDay, TripPlan


def _plan() -> TripPlan:
    return TripPlan(
        title="Tokyo plan",
        origin="Dhaka",
        destination="Japan",
        start_date=date(2026, 9, 10),
        end_date=date(2026, 9, 12),
        duration_days=2,
        travelers=1,
        guest_nationality_country_code="BD",
        preferences=[],
        days=[
            ItineraryDay(
                day_number=1,
                date=date(2026, 9, 10),
                city="Tokyo",
                activities=[Activity(name="Temple", category="culture")],
            )
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Local costs", amount_usd=300)],
            estimated_total_usd=300,
        ),
        practical_notes=[],
    )


def test_missing_liteapi_key_does_not_break_itinerary(monkeypatch):
    monkeypatch.setattr(
        hotel_recommendation,
        "get_settings",
        lambda: SimpleNamespace(LITEAPI_API_KEY=None, GEOAPIFY_API_KEY=None),
    )
    plan = _plan()

    result = asyncio.run(
        hotel_recommendation.hotel_recommendation_node(
            {"itinerary": plan},
            {},
        )
    )

    assert result["itinerary"].budget == plan.budget
    assert result["itinerary"].recommendations.hotel_status.status == "unavailable"


def test_node_without_itinerary_is_a_noop():
    result = asyncio.run(
        hotel_recommendation.hotel_recommendation_node(
            {"itinerary": None},
            {},
        )
    )

    assert result == {"itinerary": None}
