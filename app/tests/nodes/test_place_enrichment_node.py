import asyncio
from types import SimpleNamespace

from app.graph.nodes import place_enrichment
from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    ItineraryDay,
    TripPlan,
)


def _plan() -> TripPlan:
    return TripPlan(
        title="Thailand Plan",
        destination="Thailand",
        duration_days=1,
        travelers=1,
        preferences=[],
        days=[
            ItineraryDay(
                day_number=1,
                city="Bangkok",
                activities=[Activity(name="Wat Arun", category="culture")],
            )
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Activities", amount_usd=20)],
            estimated_total_usd=20,
        ),
        practical_notes=[],
    )


def test_none_itinerary_is_a_noop_without_provider_calls(monkeypatch):
    monkeypatch.setattr(
        place_enrichment,
        "build_places_provider",
        lambda key: (_ for _ in ()).throw(AssertionError("provider constructed")),
    )

    result = asyncio.run(
        place_enrichment.place_enrichment_node({"itinerary": None}, config={})
    )

    assert result == {"itinerary": None}


def test_existing_itinerary_runs_enrichment_and_closes_provider(monkeypatch):
    original = _plan()
    enriched = original.model_copy(update={"title": "Enriched Thailand Plan"})

    class Provider:
        closed = False

        async def aclose(self):
            self.closed = True

    provider = Provider()
    monkeypatch.setattr(
        place_enrichment,
        "get_settings",
        lambda: SimpleNamespace(GEOAPIFY_API_KEY="test-key"),
    )
    monkeypatch.setattr(
        place_enrichment,
        "build_places_provider",
        lambda key: provider,
    )

    async def fake_enrich(plan, selected_provider):
        assert plan is original
        assert selected_provider is provider
        return enriched

    monkeypatch.setattr(place_enrichment, "enrich_trip_places", fake_enrich)

    result = asyncio.run(
        place_enrichment.place_enrichment_node({"itinerary": original}, config={})
    )

    assert result["itinerary"].title == "Enriched Thailand Plan"
    assert provider.closed is True


def test_service_exception_preserves_original_itinerary(monkeypatch):
    original = _plan()
    monkeypatch.setattr(
        place_enrichment,
        "get_settings",
        lambda: SimpleNamespace(GEOAPIFY_API_KEY="test-key"),
    )
    monkeypatch.setattr(
        place_enrichment,
        "build_places_provider",
        lambda key: SimpleNamespace(),
    )

    async def fail(plan, provider):
        raise RuntimeError("unexpected provider failure")

    monkeypatch.setattr(place_enrichment, "enrich_trip_places", fail)

    result = asyncio.run(
        place_enrichment.place_enrichment_node({"itinerary": original}, config={})
    )

    assert result["itinerary"] is original


def test_missing_or_blank_api_key_preserves_original_itinerary(monkeypatch):
    original = _plan()
    for value in (None, "   "):
        monkeypatch.setattr(
            place_enrichment,
            "get_settings",
            lambda value=value: SimpleNamespace(GEOAPIFY_API_KEY=value),
        )

        result = asyncio.run(
            place_enrichment.place_enrichment_node(
                {"itinerary": original},
                config={},
            )
        )

        assert result["itinerary"] is original


def test_provider_construction_failure_preserves_original_itinerary(monkeypatch):
    original = _plan()
    monkeypatch.setattr(
        place_enrichment,
        "get_settings",
        lambda: SimpleNamespace(GEOAPIFY_API_KEY="test-key"),
    )
    monkeypatch.setattr(
        place_enrichment,
        "build_places_provider",
        lambda key: (_ for _ in ()).throw(RuntimeError("construction failed")),
    )

    result = asyncio.run(
        place_enrichment.place_enrichment_node({"itinerary": original}, config={})
    )

    assert result["itinerary"] is original
