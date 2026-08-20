import asyncio
from datetime import date
from types import SimpleNamespace

from app.graph.nodes import flight_recommendation
from app.models import Activity, BudgetBreakdown, BudgetItem, ItineraryDay, TripPlan


def _plan() -> TripPlan:
    return TripPlan(
        title="Plan",
        origin="Dhaka",
        destination="Japan",
        start_date=date(2026, 9, 10),
        end_date=date(2026, 9, 12),
        duration_days=3,
        travelers=1,
        preferences=[],
        days=[
            ItineraryDay(
                day_number=1,
                city="Tokyo",
                activities=[Activity(name="Temple", category="culture")],
            )
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Trip", amount_usd=900)],
            estimated_total_usd=900,
            user_budget_usd=1000,
        ),
        practical_notes=[],
    )


def test_missing_geoapify_key_marks_flights_unavailable_without_dropping_plan(
    monkeypatch,
):
    monkeypatch.setattr(
        flight_recommendation,
        "get_settings",
        lambda: SimpleNamespace(GEOAPIFY_API_KEY=" "),
    )

    result = asyncio.run(
        flight_recommendation.flight_recommendation_node(
            {"itinerary": _plan()},
            config={},
        )
    )

    assert result["itinerary"].title == "Plan"
    assert result["itinerary"].recommendations.flight_status.status == "unavailable"


def test_provider_failure_is_graceful_and_provider_is_closed(monkeypatch):
    class Provider:
        closed = False

        async def search_flights(self, request):
            raise TimeoutError("supplier timeout")

        async def aclose(self):
            self.closed = True

    provider = Provider()
    monkeypatch.setattr(
        flight_recommendation,
        "get_settings",
        lambda: SimpleNamespace(GEOAPIFY_API_KEY="private-geoapify-key"),
    )
    monkeypatch.setattr(
        flight_recommendation,
        "build_flight_provider",
        lambda api_key: provider,
    )

    result = asyncio.run(
        flight_recommendation.flight_recommendation_node(
            {"itinerary": _plan()},
            config={},
        )
    )

    assert result["itinerary"].title == "Plan"
    assert result["itinerary"].recommendations.flight_status.status == "unavailable"
    assert provider.closed is True


def test_successful_empty_swoop_search_is_no_results_and_provider_is_closed(
    monkeypatch,
):
    class Provider:
        closed = False

        async def search_flights(self, request):
            return []

        async def aclose(self):
            self.closed = True

    provider = Provider()
    monkeypatch.setattr(
        flight_recommendation,
        "get_settings",
        lambda: SimpleNamespace(GEOAPIFY_API_KEY="private-geoapify-key"),
    )
    monkeypatch.setattr(
        flight_recommendation,
        "build_flight_provider",
        lambda api_key: provider,
    )

    result = asyncio.run(
        flight_recommendation.flight_recommendation_node(
            {"itinerary": _plan()},
            config={},
        )
    )

    assert result["itinerary"].recommendations.flight_status.status == "no_results"
    assert provider.closed is True
