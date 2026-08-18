import asyncio

import httpx
import pytest

from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    ItineraryDay,
    ResolvedPlace,
    TripPlan,
)
from app.services.place_enrichment import (
    enrich_trip_places,
    should_resolve_activity_place,
)
from app.services.places import PlaceResolution, PlacesProviderUnavailableError
from app.services.places.geoapify import GeoapifyPlacesProvider


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
    assert provider.calls == ["Wat Mahathat", "Wat Phra Si Sanphet"]


def test_no_result_does_not_open_provider_circuit():
    plan = _plan(
        Activity(name="Unknown Temple", category="history"),
        Activity(name="Wat Mahathat", category="history"),
    )
    provider = FakeProvider({"Wat Mahathat": _resolution("Wat Mahathat")})

    enriched = asyncio.run(enrich_trip_places(plan, provider))

    assert provider.calls == ["Unknown Temple", "Wat Mahathat"]
    assert enriched.days[0].activities[0].place is None
    assert enriched.days[0].activities[1].place is not None


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


class UnavailableProvider:
    def __init__(self):
        self.calls = []

    async def resolve_place(self, *, name, location_hint, city, destination):
        self.calls.append(name)
        raise PlacesProviderUnavailableError("provider unavailable")


def test_provider_wide_failure_opens_trip_local_circuit():
    plan = _plan(
        Activity(name="Wat Mahathat", category="history"),
        Activity(name="Wat Phra Si Sanphet", category="history"),
        Activity(name="Wat Ratchaburana", category="history"),
    )
    provider = UnavailableProvider()

    enriched = asyncio.run(enrich_trip_places(plan, provider, concurrency_limit=3))

    assert provider.calls == ["Wat Mahathat"]
    assert all(activity.place is None for activity in enriched.days[0].activities)


@pytest.mark.parametrize(
    ("status_code", "expected_requests"),
    [(401, 1), (403, 1), (429, 3), (500, 3)],
)
def test_geoapify_provider_wide_http_failure_is_not_multiplied(
    status_code,
    expected_requests,
):
    request_count = 0

    def handler(request):
        nonlocal request_count
        request_count += 1
        return httpx.Response(status_code, json={"message": "provider failure"})

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            provider = GeoapifyPlacesProvider(
                "test-key",
                client=client,
                sleep=lambda _: asyncio.sleep(0),
            )
            return await enrich_trip_places(
                _plan(
                    Activity(name="Wat Mahathat", category="history"),
                    Activity(name="Wat Phra Si Sanphet", category="history"),
                    Activity(name="Wat Ratchaburana", category="history"),
                ),
                provider,
                concurrency_limit=3,
            )

    enriched = asyncio.run(run())

    assert request_count == expected_requests
    assert all(activity.place is None for activity in enriched.days[0].activities)


@pytest.mark.parametrize(
    ("name", "category"),
    [
        ("Airport Transfer", "transport"),
        ("Train to Ayutthaya", "experience"),
        ("Hotel Check-in", "accommodation"),
        ("Return to Bangkok", "logistics"),
        ("Lunch at a local restaurant", "food"),
    ],
)
def test_non_place_activities_are_not_eligible(name, category):
    assert should_resolve_activity_place(Activity(name=name, category=category)) is False


@pytest.mark.parametrize(
    ("name", "category"),
    [
        ("Wat Mahathat", "history"),
        ("Erawan National Park", "nature"),
        ("Bridge over the River Kwai", "landmark"),
        ("Chatuchak Weekend Market", "shopping"),
    ],
)
def test_named_place_activities_remain_eligible(name, category):
    assert should_resolve_activity_place(Activity(name=name, category=category)) is True


def test_enrichment_calls_provider_only_for_place_activities():
    plan = _plan(
        Activity(name="Wat Mahathat", category="history"),
        Activity(name="Airport Transfer", category="transport"),
        Activity(name="Lunch", category="dining"),
    )
    provider = FakeProvider({"Wat Mahathat": _resolution("Wat Mahathat")})

    enriched = asyncio.run(enrich_trip_places(plan, provider))

    assert provider.calls == ["Wat Mahathat"]
    assert enriched.days[0].activities[0].place is not None
    assert all(activity.place is None for activity in enriched.days[0].activities[1:])
