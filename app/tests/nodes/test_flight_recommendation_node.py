import asyncio
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.graph.nodes import flight_recommendation
from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    FlightOption,
    FlightSearchCache,
    FlightSegment,
    FlightSlice,
    ItineraryDay,
    RecommendationDomainState,
    ResolvedPlace,
    TripPlan,
)
from app.services.flight_recommendation import build_flight_search_request


def _plan() -> TripPlan:
    return TripPlan(
        title="Plan",
        origin="Dhaka",
        destination="Japan",
        start_date=date(2026, 9, 10),
        end_date=date(2026, 9, 12),
        duration_days=3,
        travelers=2,
        preferences=[],
        days=[
            ItineraryDay(
                day_number=1,
                city="Tokyo",
                activities=[
                    Activity(
                        name="Temple",
                        category="culture",
                        place=ResolvedPlace(
                            provider="geoapify",
                            provider_place_id="tokyo",
                            name="Tokyo",
                            country_code="JP",
                            latitude=35.6762,
                            longitude=139.6503,
                            resolution_status="resolved",
                        ),
                        place_resolution_status="resolved",
                    )
                ],
            ),
            ItineraryDay(
                day_number=3,
                city="Osaka",
                activities=[
                    Activity(
                        name="Castle",
                        category="culture",
                        place=ResolvedPlace(
                            provider="geoapify",
                            provider_place_id="osaka",
                            name="Osaka",
                            country_code="JP",
                            latitude=34.6937,
                            longitude=135.5023,
                            resolution_status="resolved",
                        ),
                        place_resolution_status="resolved",
                    )
                ],
            )
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Trip", amount_usd=900)],
            estimated_total_usd=900,
            user_budget_usd=1000,
        ),
        practical_notes=[],
    )


def _flight(offer_id: str = "flight_abc", price: float = 714.20) -> FlightOption:
    departure = datetime(2026, 9, 10, 2, tzinfo=UTC)
    arrival = departure + timedelta(hours=7)
    segment = FlightSegment(
        origin_code="DAC",
        destination_code="HND",
        departure_at=departure,
        arrival_at=arrival,
        duration_minutes=420,
        airline_name="Example Airways",
    )
    return FlightOption(
        provider="swoop",
        provider_offer_id=offer_id,
        origin_code="DAC",
        destination_code="HND",
        adults=2,
        total_duration_minutes=420,
        stops=0,
        total_price=price,
        currency="USD",
        price_type="shopping_total",
        airline_names=["Example Airways"],
        slices=[
            FlightSlice(
                origin_code="DAC",
                destination_code="HND",
                departure_at=departure,
                arrival_at=arrival,
                duration_minutes=420,
                stops=0,
                segments=[segment],
            )
        ],
        fetched_at=datetime(2026, 8, 22, tzinfo=UTC),
    )


def _cache(
    plan: TripPlan,
    *,
    status: str = "available",
    age_minutes: int = 5,
) -> FlightSearchCache:
    request = build_flight_search_request(plan)
    assert request is not None
    available = status == "available"
    return FlightSearchCache(
        request=request,
        flights=[_flight()] if available else [],
        status=RecommendationDomainState(
            status=status,
            provider_result_count=1 if available else 0,
        ),
        searched_at=datetime.now(UTC) - timedelta(minutes=age_minutes),
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
    assert result["flight_search_cache"].status.status == "no_results"
    assert result["flight_search_cache"].flights == []
    assert provider.closed is True


@pytest.mark.parametrize("change", ["budget", "activity"])
def test_fresh_cache_reattaches_to_new_plan_without_constructing_provider(
    monkeypatch,
    change,
):
    old_plan = _plan()
    new_plan = old_plan.model_copy(deep=True)
    if change == "budget":
        new_plan.budget.user_budget_usd = 3000
    else:
        new_plan.days[0].activities.append(
            Activity(name="Another temple", category="culture")
        )

    cache = _cache(old_plan)
    monkeypatch.setattr(
        flight_recommendation,
        "get_settings",
        lambda: pytest.fail("settings/provider path must not run on cache hit"),
    )
    monkeypatch.setattr(
        flight_recommendation,
        "build_flight_provider",
        lambda api_key: pytest.fail("airport resolver must not be constructed"),
    )

    result = asyncio.run(
        flight_recommendation.flight_recommendation_node(
            {"itinerary": new_plan, "flight_search_cache": cache},
            config={},
        )
    )

    attached = result["itinerary"].recommendations.flights[0]
    assert result["itinerary"] is not old_plan
    assert attached.provider_offer_id == "flight_abc"
    assert attached.total_price == 714.20
    assert result["flight_search_cache"] == cache


def test_fresh_no_results_cache_skips_provider(monkeypatch):
    plan = _plan()
    monkeypatch.setattr(
        flight_recommendation,
        "build_flight_provider",
        lambda api_key: pytest.fail("provider must not run"),
    )
    monkeypatch.setattr(
        flight_recommendation,
        "get_settings",
        lambda: pytest.fail("settings must not be needed"),
    )

    result = asyncio.run(
        flight_recommendation.flight_recommendation_node(
            {
                "itinerary": plan,
                "flight_search_cache": _cache(plan, status="no_results"),
            },
            config={},
        )
    )

    assert result["itinerary"].recommendations.flights == []
    assert result["itinerary"].recommendations.flight_status.status == "no_results"


@pytest.mark.parametrize(
    "change",
    ["expired", "origin", "dates", "travelers", "first_city", "final_city", "hint"],
)
def test_expired_or_changed_request_runs_provider_and_replaces_cache(
    monkeypatch,
    change,
):
    cached_plan = _plan()
    current_plan = cached_plan.model_copy(deep=True)
    age_minutes = 16 if change == "expired" else 5
    if change == "origin":
        current_plan.origin = "Chittagong"
    elif change == "dates":
        current_plan.start_date = date(2026, 9, 15)
        current_plan.end_date = date(2026, 9, 17)
    elif change == "travelers":
        current_plan.travelers = 3
    elif change == "first_city":
        current_plan.days[0].city = "Nagoya"
    elif change == "final_city":
        current_plan.days[-1].city = "Hiroshima"
    elif change == "hint":
        current_plan.days[0].activities[0].place.country_code = "KR"

    class Provider:
        calls = 0
        closed = False

        async def search_flights(self, request):
            self.calls += 1
            return [_flight("fresh_flight", 800)]

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
            {
                "itinerary": current_plan,
                "flight_search_cache": _cache(
                    cached_plan,
                    age_minutes=age_minutes,
                ),
            },
            config={},
        )
    )

    expected_request = build_flight_search_request(current_plan)
    assert provider.calls == 1
    assert provider.closed is True
    assert result["flight_search_cache"].request == expected_request
    assert result["flight_search_cache"].flights[0].provider_offer_id == "fresh_flight"


def test_unavailable_cache_is_not_reused(monkeypatch):
    plan = _plan()

    class Provider:
        calls = 0

        async def search_flights(self, request):
            self.calls += 1
            return []

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
            {
                "itinerary": plan,
                "flight_search_cache": _cache(plan, status="unavailable"),
            },
            config={},
        )
    )

    assert provider.calls == 1
    assert result["flight_search_cache"].status.status == "no_results"


def test_failed_search_for_changed_request_does_not_replace_old_cache(monkeypatch):
    cached_plan = _plan()
    current_plan = cached_plan.model_copy(deep=True)
    current_plan.origin = "Chittagong"
    old_cache = _cache(cached_plan)

    class Provider:
        async def search_flights(self, request):
            raise TimeoutError("temporary provider failure")

    monkeypatch.setattr(
        flight_recommendation,
        "get_settings",
        lambda: SimpleNamespace(GEOAPIFY_API_KEY="private-geoapify-key"),
    )
    monkeypatch.setattr(
        flight_recommendation,
        "build_flight_provider",
        lambda api_key: Provider(),
    )

    result = asyncio.run(
        flight_recommendation.flight_recommendation_node(
            {
                "itinerary": current_plan,
                "flight_search_cache": old_cache,
            },
            config={},
        )
    )

    assert "flight_search_cache" not in result
    assert old_cache.request == build_flight_search_request(cached_plan)
    assert result["itinerary"].recommendations.flight_status.status == "unavailable"
