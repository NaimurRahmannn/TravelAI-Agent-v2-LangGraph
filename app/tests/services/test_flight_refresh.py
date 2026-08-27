import asyncio
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    ConfirmedTripSnapshot,
    DetailedRoutingDay,
    DetailedRoutingPlan,
    FlightOption,
    FlightSearchCache,
    FlightSegment,
    FlightSlice,
    ItineraryDay,
    RecommendationDomainState,
    TravelSelections,
    TripCostSummary,
    TravelRecommendations,
    TripPlan,
)
from app.schemas.api import FlightRefreshRequest
from app.services.flight_recommendation import build_flight_search_request
from app.services.flight_refresh import FlightRefreshError, FlightRefreshService


def _flight(offer_id: str, price: float) -> FlightOption:
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


def _plan(flight: FlightOption) -> TripPlan:
    return TripPlan(
        title="Japan plan",
        origin="Dhaka",
        destination="Japan",
        start_date=date(2026, 9, 10),
        end_date=date(2026, 9, 15),
        duration_days=6,
        travelers=2,
        preferences=["temples"],
        days=[
            ItineraryDay(
                day_number=1,
                city="Tokyo",
                activities=[Activity(name="Temple", category="culture")],
            ),
            ItineraryDay(
                day_number=6,
                city="Osaka",
                activities=[Activity(name="Castle", category="culture")],
            ),
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Activities", amount_usd=500)],
            estimated_total_usd=500,
            user_budget_usd=2000,
        ),
        recommendations=TravelRecommendations(
            flights=[flight],
            flight_status=RecommendationDomainState(
                status="available",
                provider_result_count=1,
            ),
        ),
        practical_notes=["Keep documents handy."],
    )


def _cache(plan: TripPlan) -> FlightSearchCache:
    request = build_flight_search_request(plan)
    assert request is not None
    assert plan.recommendations is not None
    return FlightSearchCache(
        request=request,
        flights=plan.recommendations.flights,
        status=plan.recommendations.flight_status,
        searched_at=datetime.now(UTC) - timedelta(minutes=1),
    )


class FakeGraph:
    def __init__(self, values):
        self.values = values
        self.updates = []
        self.invoke_calls = 0

    async def aget_state(self, config):
        return SimpleNamespace(values=self.values, created_at="now")

    async def aupdate_state(self, config, values, *, as_node):
        self.updates.append((config, values, as_node))
        self.values.update(values)

    async def ainvoke(self, *args, **kwargs):
        self.invoke_calls += 1
        pytest.fail("Explicit flight refresh must not invoke the travel graph")


def _install(monkeypatch, graph: FakeGraph, provider) -> None:
    async def get_fake_graph():
        return graph

    monkeypatch.setattr(
        FlightRefreshService,
        "_get_graph",
        staticmethod(get_fake_graph),
    )
    monkeypatch.setattr(
        FlightRefreshService,
        "_build_provider",
        staticmethod(lambda api_key: provider),
    )
    monkeypatch.setattr(
        "app.services.flight_refresh.get_settings",
        lambda: SimpleNamespace(GEOAPIFY_API_KEY="private-geoapify-key"),
    )


def test_explicit_refresh_bypasses_fresh_cache_and_preserves_confirmed_state(
    monkeypatch,
):
    old_plan = _plan(_flight("old-flight", 714.20))
    old_cache = _cache(old_plan)
    selections = TravelSelections(selected_flight_id="old-flight")
    cost_summary = TripCostSummary(
        base_trip_total_usd=500,
        selected_flight_usd=714.20,
        selected_hotels_usd=0,
        additions_total_usd=714.20,
        updated_trip_total_usd=1214.20,
    )
    routing_plan = DetailedRoutingPlan(
        days=[DetailedRoutingDay(day_number=1, date=date(2026, 9, 10))],
        generated_at=datetime(2026, 8, 22, tzinfo=UTC),
        has_ai_estimates=False,
    )
    confirmed = ConfirmedTripSnapshot(
        revision=1,
        itinerary=old_plan,
        selections=selections,
        cost_summary=cost_summary,
        routing_plan=routing_plan,
    )
    graph = FakeGraph(
        {
            "itinerary": old_plan,
            "flight_search_cache": old_cache,
            "travel_selections": selections,
            "trip_cost_summary": cost_summary,
            "detailed_routing_plan": routing_plan,
            "confirmed_snapshot": confirmed,
        }
    )

    class Provider:
        calls = 0
        closed = False

        async def search_flights(self, request):
            self.calls += 1
            return [_flight("fresh-flight", 800)]

        async def aclose(self):
            self.closed = True

    provider = Provider()
    _install(monkeypatch, graph, provider)

    response = asyncio.run(
        FlightRefreshService().refresh(
            FlightRefreshRequest(thread_id="thread-a")
        )
    )

    assert provider.calls == 1
    assert provider.closed is True
    assert graph.invoke_calls == 0
    assert len(graph.updates) == 1
    _, update, as_node = graph.updates[0]
    assert as_node == "memory_write"
    assert update["itinerary"].title == old_plan.title
    assert update["itinerary"].days == old_plan.days
    assert update["itinerary"].budget == old_plan.budget
    assert update["itinerary"].recommendations.flights[0].provider_offer_id == (
        "fresh-flight"
    )
    assert update["flight_search_cache"].request == old_cache.request
    assert update["flight_search_cache"].flights[0].total_price == 800
    assert "travel_selections" not in update
    assert "trip_cost_summary" not in update
    assert "detailed_routing_plan" not in update
    assert "confirmed_snapshot" not in update
    assert response.itinerary == update["itinerary"]
    assert response.travel_selections == selections
    assert response.trip_cost_summary == cost_summary
    assert response.detailed_routing_plan == routing_plan
    assert response.confirmed_snapshot == confirmed


def test_successful_empty_refresh_replaces_cache_with_no_results(monkeypatch):
    old_plan = _plan(_flight("old-flight", 714.20))
    graph = FakeGraph(
        {"itinerary": old_plan, "flight_search_cache": _cache(old_plan)}
    )

    class Provider:
        async def search_flights(self, request):
            return []

    _install(monkeypatch, graph, Provider())

    response = asyncio.run(
        FlightRefreshService().refresh(
            FlightRefreshRequest(thread_id="thread-a")
        )
    )

    assert response.itinerary.recommendations.flights == []
    assert response.itinerary.recommendations.flight_status.status == "no_results"
    assert graph.values["flight_search_cache"].flights == []
    assert graph.values["flight_search_cache"].status.status == "no_results"


def test_explicit_refresh_updates_both_split_candidate_sets(monkeypatch):
    plan = _plan(_flight("legacy", 700))
    assert plan.recommendations is not None
    plan.recommendations.flights = []
    plan.recommendations.outbound_flights = [_flight("old-outbound", 500)]
    plan.recommendations.return_flights = [_flight("old-return", 400)]
    plan.recommendations.outbound_flight_status = RecommendationDomainState(
        status="available",
        provider_result_count=1,
    )
    plan.recommendations.return_flight_status = RecommendationDomainState(
        status="available",
        provider_result_count=1,
    )
    graph = FakeGraph({"itinerary": plan, "flight_search_cache": None})

    class Provider:
        requests = []

        async def search_flights(self, request):
            self.requests.append(request)
            return [
                _flight(
                    "fresh-outbound" if len(self.requests) == 1 else "fresh-return",
                    550 if len(self.requests) == 1 else 450,
                )
            ]

    provider = Provider()
    _install(monkeypatch, graph, provider)

    response = asyncio.run(
        FlightRefreshService().refresh(
            FlightRefreshRequest(thread_id="thread-a")
        )
    )

    assert len(provider.requests) == 2
    assert provider.requests[0].return_date is None
    assert provider.requests[1].departure_date == plan.end_date
    assert response.itinerary.recommendations.outbound_flights[0].provider_offer_id == (
        "fresh-outbound"
    )
    assert response.itinerary.recommendations.return_flights[0].provider_offer_id == (
        "fresh-return"
    )
    assert graph.values["flight_search_cache"] is None


def test_refresh_failure_preserves_previous_cache_and_recommendations(monkeypatch):
    old_plan = _plan(_flight("old-flight", 714.20))
    old_cache = _cache(old_plan)
    graph = FakeGraph(
        {"itinerary": old_plan, "flight_search_cache": old_cache}
    )

    class Provider:
        closed = False

        async def search_flights(self, request):
            raise TimeoutError("temporary upstream failure")

        async def aclose(self):
            self.closed = True

    provider = Provider()
    _install(monkeypatch, graph, provider)

    with pytest.raises(
        FlightRefreshError,
        match="previous flight recommendations are still available",
    ):
        asyncio.run(
            FlightRefreshService().refresh(
                FlightRefreshRequest(thread_id="thread-a")
            )
        )

    assert provider.closed is True
    assert graph.updates == []
    assert graph.values["flight_search_cache"] is old_cache
    assert graph.values["itinerary"] is old_plan
    assert old_plan.recommendations.flights[0].provider_offer_id == "old-flight"


def test_refresh_request_accepts_only_thread_lookup_identity():
    with pytest.raises(ValidationError):
        FlightRefreshRequest(
            thread_id="thread-a",
            origin="Dhaka",
        )
