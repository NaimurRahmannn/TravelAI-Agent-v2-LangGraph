import asyncio
from types import SimpleNamespace

from app.graph.nodes import routing_enrichment
from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    ItineraryDay,
    ResolvedPlace,
    TripPlan,
)


def _plan() -> TripPlan:
    activities = []
    for place_id, latitude in (("first", 13.75), ("second", 13.80)):
        place = ResolvedPlace(
            provider="geoapify",
            provider_place_id=place_id,
            name=place_id,
            latitude=latitude,
            longitude=100.5,
            resolution_status="resolved",
        )
        activities.append(
            Activity(
                name=place_id,
                category="visit",
                place=place,
                place_resolution_status="resolved",
            )
        )
    return TripPlan(
        title="Plan",
        destination="Thailand",
        duration_days=1,
        travelers=1,
        preferences=[],
        days=[ItineraryDay(day_number=1, city="Bangkok", activities=activities)],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Activities", amount_usd=20)],
            estimated_total_usd=20,
        ),
        practical_notes=[],
    )


def test_missing_api_key_preserves_eligible_plan(monkeypatch):
    original = _plan()
    monkeypatch.setattr(
        routing_enrichment,
        "get_settings",
        lambda: SimpleNamespace(GEOAPIFY_API_KEY=" "),
    )

    result = asyncio.run(
        routing_enrichment.routing_enrichment_node(
            {"itinerary": original},
            config={},
        )
    )

    assert result["itinerary"] is original


def test_enrichment_failure_preserves_plan_and_closes_provider(monkeypatch):
    original = _plan()

    class Provider:
        closed = False

        async def aclose(self):
            self.closed = True

    provider = Provider()
    monkeypatch.setattr(
        routing_enrichment,
        "get_settings",
        lambda: SimpleNamespace(GEOAPIFY_API_KEY="private-key"),
    )
    monkeypatch.setattr(
        routing_enrichment,
        "build_routing_provider",
        lambda api_key: provider,
    )

    async def fail(plan, selected_provider):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(routing_enrichment, "enrich_trip_routes", fail)

    result = asyncio.run(
        routing_enrichment.routing_enrichment_node(
            {"itinerary": original},
            config={},
        )
    )

    assert result["itinerary"] is original
    assert provider.closed is True
