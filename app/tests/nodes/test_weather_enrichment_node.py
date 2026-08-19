import asyncio
from datetime import date
from types import SimpleNamespace

from app.graph.nodes import weather_enrichment
from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    ItineraryDay,
    ResolvedPlace,
    TripPlan,
)


def _plan(*, dated: bool = True, resolved: bool = True) -> TripPlan:
    place = None
    status = "unresolved"
    if resolved:
        place = ResolvedPlace(
            provider="geoapify",
            provider_place_id="wat-arun",
            name="Wat Arun",
            city="Bangkok",
            country="Thailand",
            latitude=13.7437,
            longitude=100.4889,
            resolution_status="resolved",
        )
        status = "resolved"
    return TripPlan(
        title="Thailand Plan",
        destination="Thailand",
        duration_days=1,
        travelers=1,
        preferences=[],
        days=[
            ItineraryDay(
                day_number=1,
                date=date(2026, 8, 21) if dated else None,
                city="Bangkok",
                activities=[
                    Activity(
                        name="Wat Arun",
                        category="culture",
                        place=place,
                        place_resolution_status=status,
                    )
                ],
            )
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Activities", amount_usd=20)],
            estimated_total_usd=20,
        ),
        practical_notes=[],
    )


def test_none_itinerary_is_noop_without_provider(monkeypatch):
    monkeypatch.setattr(
        weather_enrichment,
        "build_weather_provider",
        lambda value: (_ for _ in ()).throw(AssertionError("provider constructed")),
    )

    result = asyncio.run(
        weather_enrichment.weather_enrichment_node({"itinerary": None}, config={})
    )

    assert result == {"itinerary": None}


def test_plan_without_eligible_day_is_noop_without_provider(monkeypatch):
    original = _plan(dated=False)
    monkeypatch.setattr(
        weather_enrichment,
        "build_weather_provider",
        lambda value: (_ for _ in ()).throw(AssertionError("provider constructed")),
    )

    result = asyncio.run(
        weather_enrichment.weather_enrichment_node(
            {"itinerary": original}, config={}
        )
    )

    assert result["itinerary"] is original


def test_missing_api_key_preserves_plan(monkeypatch):
    original = _plan()
    monkeypatch.setattr(
        weather_enrichment,
        "get_settings",
        lambda: SimpleNamespace(OPENWEATHER_API_KEY="   "),
    )

    result = asyncio.run(
        weather_enrichment.weather_enrichment_node(
            {"itinerary": original}, config={}
        )
    )

    assert result["itinerary"] is original


def test_eligible_plan_runs_enrichment_and_closes_provider(monkeypatch):
    original = _plan()
    enriched = original.model_copy(update={"title": "Enriched"})

    class Provider:
        closed = False

        async def aclose(self):
            self.closed = True

    provider = Provider()
    monkeypatch.setattr(
        weather_enrichment,
        "get_settings",
        lambda: SimpleNamespace(OPENWEATHER_API_KEY="server-only-key"),
    )
    monkeypatch.setattr(
        weather_enrichment,
        "build_weather_provider",
        lambda value: provider,
    )

    async def fake_enrich(plan, selected_provider):
        assert plan is original
        assert selected_provider is provider
        return enriched

    monkeypatch.setattr(weather_enrichment, "enrich_trip_weather", fake_enrich)

    result = asyncio.run(
        weather_enrichment.weather_enrichment_node(
            {"itinerary": original}, config={}
        )
    )

    assert result["itinerary"].title == "Enriched"
    assert provider.closed is True


def test_service_failure_preserves_original_plan_and_closes_provider(monkeypatch):
    original = _plan()

    class Provider:
        closed = False

        async def aclose(self):
            self.closed = True

    provider = Provider()
    monkeypatch.setattr(
        weather_enrichment,
        "get_settings",
        lambda: SimpleNamespace(OPENWEATHER_API_KEY="server-only-key"),
    )
    monkeypatch.setattr(
        weather_enrichment,
        "build_weather_provider",
        lambda value: provider,
    )

    async def fail(plan, selected_provider):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(weather_enrichment, "enrich_trip_weather", fail)

    result = asyncio.run(
        weather_enrichment.weather_enrichment_node(
            {"itinerary": original}, config={}
        )
    )

    assert result["itinerary"] is original
    assert provider.closed is True
