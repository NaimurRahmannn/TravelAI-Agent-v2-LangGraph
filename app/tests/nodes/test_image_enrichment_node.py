import asyncio
from types import SimpleNamespace

from app.graph.nodes import image_enrichment
from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    ItineraryDay,
    ResolvedPlace,
    TripPlan,
)


def _plan(*, resolved=True) -> TripPlan:
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
                city="Bangkok",
                activities=[
                    Activity(
                        name="Wat Arun" if resolved else "Airport Transfer",
                        category="culture" if resolved else "transport",
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
        image_enrichment,
        "build_image_provider",
        lambda value: (_ for _ in ()).throw(AssertionError("provider constructed")),
    )

    result = asyncio.run(
        image_enrichment.image_enrichment_node({"itinerary": None}, config={})
    )

    assert result == {"itinerary": None}


def test_plan_without_eligible_places_is_noop_without_provider(monkeypatch):
    original = _plan(resolved=False)
    monkeypatch.setattr(
        image_enrichment,
        "build_image_provider",
        lambda value: (_ for _ in ()).throw(AssertionError("provider constructed")),
    )

    result = asyncio.run(
        image_enrichment.image_enrichment_node({"itinerary": original}, config={})
    )

    assert result["itinerary"] is original


def test_missing_pexels_api_key_preserves_plan(monkeypatch):
    original = _plan()
    monkeypatch.setattr(
        image_enrichment,
        "get_settings",
        lambda: SimpleNamespace(PEXELS_API_KEY="   "),
    )

    result = asyncio.run(
        image_enrichment.image_enrichment_node({"itinerary": original}, config={})
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
        image_enrichment,
        "get_settings",
        lambda: SimpleNamespace(PEXELS_API_KEY="pexels-test-key"),
    )
    monkeypatch.setattr(
        image_enrichment,
        "build_image_provider",
        lambda value: provider,
    )

    async def fake_enrich(plan, selected_provider):
        assert plan is original
        assert selected_provider is provider
        return enriched

    monkeypatch.setattr(image_enrichment, "enrich_trip_images", fake_enrich)

    result = asyncio.run(
        image_enrichment.image_enrichment_node({"itinerary": original}, config={})
    )

    assert result["itinerary"].title == "Enriched"
    assert provider.closed is True


def test_service_failure_preserves_original_plan(monkeypatch):
    original = _plan()
    monkeypatch.setattr(
        image_enrichment,
        "get_settings",
        lambda: SimpleNamespace(PEXELS_API_KEY="pexels-test-key"),
    )
    monkeypatch.setattr(
        image_enrichment,
        "build_image_provider",
        lambda value: SimpleNamespace(),
    )

    async def fail(plan, provider):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(image_enrichment, "enrich_trip_images", fail)

    result = asyncio.run(
        image_enrichment.image_enrichment_node({"itinerary": original}, config={})
    )

    assert result["itinerary"] is original
