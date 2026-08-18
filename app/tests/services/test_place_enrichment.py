import asyncio

from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    ItineraryDay,
    ResolvedPlace,
    TripPlan,
)
from app.services.place_enrichment import enrich_trip_places
from app.services.places import PlaceResolution


def _plan(*activities: Activity) -> TripPlan:
    return TripPlan(
        title="Thailand Plan",
        origin="Dhaka",
        destination="Thailand",
        duration_days=1,
        travelers=2,
        summary=None,
        preferences=[],
        days=[
            ItineraryDay(
                day_number=1,
                city="Ayutthaya",
                activities=list(activities),
            )
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Activities", amount_usd=100)],
            estimated_total_usd=100,
            user_budget_usd=500,
        ),
        practical_notes=[],
    )


def _resolution(name: str, status: str = "resolved") -> PlaceResolution:
    return PlaceResolution(
        status=status,
        place=ResolvedPlace(
            provider="geoapify",
            provider_place_id=f"id-{name}",
            name=name,
            formatted_address=f"{name}, Ayutthaya, Thailand",
            city="Ayutthaya",
            country="Thailand",
            country_code="th",
            latitude=14.35,
            longitude=100.56,
            categories=["tourism.sights"],
            confidence=0.9,
            resolution_status=status,
            source_attribution="OpenStreetMap contributors",
        ),
    )


class FakeProvider:
    def __init__(self, results=None, failures=None, delay=0):
        self.results = results or {}
        self.failures = set(failures or [])
        self.delay = delay
        self.calls = []
        self.active = 0
        self.max_active = 0

    async def resolve_place(self, *, name, location_hint, city, destination):
        self.calls.append(name)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if name in self.failures:
                raise TimeoutError("provider unavailable")
            return self.results.get(name, PlaceResolution.unresolved())
        finally:
            self.active -= 1


def test_enrichment_resolves_all_activities_without_mutating_original():
    original = _plan(
        Activity(name="Wat Mahathat", category="history"),
        Activity(name="Wat Phra Si Sanphet", category="history"),
    )
    provider = FakeProvider(
        {
            "Wat Mahathat": _resolution("Wat Mahathat"),
            "Wat Phra Si Sanphet": _resolution("Wat Phra Si Sanphet"),
        }
    )

    enriched = asyncio.run(enrich_trip_places(original, provider))

    assert original.days[0].activities[0].place is None
    assert [activity.name for activity in enriched.days[0].activities] == [
        "Wat Mahathat",
        "Wat Phra Si Sanphet",
    ]
    assert all(
        activity.place_resolution_status == "resolved"
        for activity in enriched.days[0].activities
    )


def test_partial_success_preserves_resolved_and_unresolved_activities():
    plan = _plan(
        Activity(name="Wat Mahathat", category="history"),
        Activity(name="Hidden Forest Temple", category="history"),
    )
    provider = FakeProvider({"Wat Mahathat": _resolution("Wat Mahathat")})

    enriched = asyncio.run(enrich_trip_places(plan, provider))

    assert enriched.days[0].activities[0].place is not None
    assert enriched.days[0].activities[1].place is None
    assert enriched.days[0].activities[1].place_resolution_status == "unresolved"


def test_provider_failure_preserves_usable_plan():
    plan = _plan(
        Activity(name="Wat Mahathat", category="history"),
        Activity(name="Wat Phra Si Sanphet", category="history"),
    )
    provider = FakeProvider(failures={"Wat Mahathat", "Wat Phra Si Sanphet"})

    enriched = asyncio.run(enrich_trip_places(plan, provider))

    assert [activity.name for activity in enriched.days[0].activities] == [
        "Wat Mahathat",
        "Wat Phra Si Sanphet",
    ]
    assert all(activity.place is None for activity in enriched.days[0].activities)


def test_duplicate_normalized_queries_call_provider_once():
    plan = _plan(
        Activity(
            name="Wat Mahathat",
            category="history",
            location_hint="Ayutthaya, Thailand",
        ),
        Activity(
            name="wat mahathat",
            category="history",
            location_hint="AYUTTHAYA, THAILAND",
        ),
    )
    provider = FakeProvider({"Wat Mahathat": _resolution("Wat Mahathat")})

    enriched = asyncio.run(enrich_trip_places(plan, provider))

    assert provider.calls == ["Wat Mahathat"]
    assert all(activity.place is not None for activity in enriched.days[0].activities)


def test_concurrency_is_bounded_and_does_not_change_order():
    activities = [
        Activity(name=f"Place {index}", category="visit")
        for index in range(1, 4)
    ]
    provider = FakeProvider(
        {activity.name: _resolution(activity.name) for activity in activities},
        delay=0.01,
    )

    enriched = asyncio.run(
        enrich_trip_places(_plan(*activities), provider, concurrency_limit=2)
    )

    assert 1 < provider.max_active <= 2
    assert [activity.name for activity in enriched.days[0].activities] == [
        "Place 1",
        "Place 2",
        "Place 3",
    ]
