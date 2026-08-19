import asyncio

from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    ItineraryDay,
    ResolvedPlace,
    TripPlan,
)
from app.services.routing import RouteResult, RoutingProviderUnavailableError
from app.services.routing_enrichment import enrich_trip_routes


def _place(place_id: str, latitude: float, longitude: float) -> ResolvedPlace:
    return ResolvedPlace(
        provider="geoapify",
        provider_place_id=place_id,
        name=place_id,
        latitude=latitude,
        longitude=longitude,
        resolution_status="resolved",
    )


def _activity(
    place_id: str,
    latitude: float,
    longitude: float,
    *,
    mode=None,
) -> Activity:
    place = _place(place_id, latitude, longitude)
    return Activity(
        name=place_id,
        category="visit",
        travel_mode_to_next=mode,
        place=place,
        place_resolution_status="resolved",
    )


def _plan(*days: list[Activity]) -> TripPlan:
    return TripPlan(
        title="Routing plan",
        destination="Thailand",
        duration_days=len(days),
        travelers=2,
        preferences=[],
        days=[
            ItineraryDay(
                day_number=index + 1,
                city="Bangkok",
                activities=activities,
            )
            for index, activities in enumerate(days)
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Activities", amount_usd=20)],
            estimated_total_usd=20,
        ),
        practical_notes=[],
    )


class FakeProvider:
    def __init__(self, *, error_at: int | None = None):
        self.calls = []
        self.error_at = error_at
        self.active = 0
        self.max_active = 0

    async def get_route(self, **kwargs):
        self.calls.append(kwargs)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.005)
        self.active -= 1
        if self.error_at is not None and len(self.calls) >= self.error_at:
            raise RoutingProviderUnavailableError("outage")
        return RouteResult(distance_meters=1200, duration_seconds=600)


def test_routes_only_adjacent_resolved_activities_without_skipping_logistics():
    first = _activity("temple", 13.75, 100.5)
    logistics = Activity(name="Lunch", category="meal")
    third = _activity("museum", 13.77, 100.53)
    provider = FakeProvider()

    enriched = asyncio.run(enrich_trip_routes(_plan([first, logistics, third]), provider))

    assert provider.calls == []
    assert enriched.days[0].travel_legs == []


def test_mode_hint_is_preserved_and_distance_fallback_selects_walk_or_drive():
    provider = FakeProvider()
    plan = _plan(
        [
            _activity("a", 13.75, 100.5, mode="transit"),
            _activity("b", 13.751, 100.501),
            _activity("c", 13.8, 100.6),
        ]
    )

    enriched = asyncio.run(enrich_trip_routes(plan, provider))

    assert [call["mode"] for call in provider.calls] == ["transit", "drive"]
    assert [leg.mode for leg in enriched.days[0].travel_legs] == ["transit", "drive"]

    walking_provider = FakeProvider()
    walking = asyncio.run(
        enrich_trip_routes(
            _plan(
                [
                    _activity("near-a", 13.75, 100.5),
                    _activity("near-b", 13.751, 100.501),
                ]
            ),
            walking_provider,
        )
    )
    assert walking.days[0].travel_legs[0].mode == "walk"


def test_same_place_pair_is_omitted_without_provider_call():
    place = _place("same", 13.75, 100.5)
    activities = [
        Activity(
            name=name,
            category="visit",
            place=place,
            place_resolution_status="resolved",
        )
        for name in ("First stop", "Second stop")
    ]
    provider = FakeProvider()

    enriched = asyncio.run(enrich_trip_routes(_plan(activities), provider))

    assert provider.calls == []
    assert enriched.days[0].travel_legs == []


def test_identical_requests_are_deduplicated_and_reused():
    day = [
        _activity("a", 13.75, 100.5),
        _activity("b", 13.77, 100.53),
    ]
    provider = FakeProvider()

    enriched = asyncio.run(enrich_trip_routes(_plan(day, day), provider))

    assert len(provider.calls) == 1
    assert all(item.travel_legs[0].status == "resolved" for item in enriched.days)


def test_request_cap_marks_excess_legs_unavailable():
    provider = FakeProvider()
    plan = _plan(
        [
            _activity("a", 13.70, 100.40),
            _activity("b", 13.75, 100.50),
            _activity("c", 13.80, 100.60),
        ]
    )

    enriched = asyncio.run(enrich_trip_routes(plan, provider, request_limit=1))

    assert len(provider.calls) == 1
    assert [leg.status for leg in enriched.days[0].travel_legs] == [
        "resolved",
        "unavailable",
    ]


def test_concurrency_is_bounded_after_probe():
    provider = FakeProvider()
    plan = _plan(
        [
            _activity("a", 13.70, 100.40),
            _activity("b", 13.75, 100.50),
            _activity("c", 13.80, 100.60),
        ],
        [
            _activity("d", 14.00, 100.70),
            _activity("e", 14.05, 100.80),
            _activity("f", 14.10, 100.90),
        ],
    )

    asyncio.run(enrich_trip_routes(plan, provider, concurrency_limit=2))

    assert len(provider.calls) == 4
    assert provider.max_active == 2


def test_provider_outage_preserves_probe_success_and_marks_remaining_unavailable():
    provider = FakeProvider(error_at=2)
    plan = _plan(
        [
            _activity("a", 13.70, 100.40),
            _activity("b", 13.75, 100.50),
            _activity("c", 13.80, 100.60),
        ]
    )

    enriched = asyncio.run(enrich_trip_routes(plan, provider, concurrency_limit=1))

    assert [leg.status for leg in enriched.days[0].travel_legs] == [
        "resolved",
        "unavailable",
    ]
