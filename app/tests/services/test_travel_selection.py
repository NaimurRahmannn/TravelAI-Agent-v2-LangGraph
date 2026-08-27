import asyncio
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    DetailedRoutingDay,
    DetailedRoutingPlan,
    FlightOption,
    FlightSegment,
    FlightSlice,
    HotelOption,
    ItineraryDay,
    RecommendationDomainState,
    SelectedHotelStay,
    TravelRecommendations,
    TravelSelections,
    TripPlan,
    build_hotel_stay_key,
)
from app.schemas.api import FlightLegSelectionRequest, TravelSelectionRequest
from app.services.detailed_routing import DetailedRoutingService
from app.services.flight_leg_selection import FlightLegSelectionService
from app.services.recommendations.flights import SwoopFlightProvider
from app.services.recommendations.hotels import LiteApiHotelProvider
from app.services.itinerary_renderer import render_itinerary
from app.services.travel_selection import (
    TravelSelectionError,
    TravelSelectionService,
    calculate_trip_cost_summary,
)

FETCHED_AT = datetime(2026, 8, 21, tzinfo=UTC)
START_DATE = date(2026, 9, 10)
CITIES = ("Tokyo", "Kyoto", "Osaka")
HOTEL_PRICES = (420, 280, 220)


def _flight(offer_id: str, price: float) -> FlightOption:
    departure = datetime(2026, 9, 10, 3, tzinfo=UTC)
    arrival = datetime(2026, 9, 10, 9, tzinfo=UTC)
    segment = FlightSegment(
        origin_code="DAC",
        destination_code="NRT",
        departure_at=departure,
        arrival_at=arrival,
        duration_minutes=360,
        airline_name=f"Airline {offer_id}",
    )
    return FlightOption(
        provider="swoop",
        provider_offer_id=offer_id,
        origin_code="DAC",
        destination_code="NRT",
        adults=2,
        total_duration_minutes=360,
        stops=0,
        total_price=price,
        currency="USD",
        price_type="shopping_total",
        airline_names=[f"Airline {offer_id}"],
        slices=[
            FlightSlice(
                origin_code="DAC",
                destination_code="NRT",
                departure_at=departure,
                arrival_at=arrival,
                duration_minutes=360,
                stops=0,
                segments=[segment],
            )
        ],
        fetched_at=FETCHED_AT,
    )


def _return_flight(offer_id: str, price: float) -> FlightOption:
    departure = datetime(2026, 9, 13, 3, tzinfo=UTC)
    arrival = datetime(2026, 9, 13, 11, tzinfo=UTC)
    segment = FlightSegment(
        origin_code="KIX",
        destination_code="DAC",
        departure_at=departure,
        arrival_at=arrival,
        duration_minutes=480,
        airline_name=f"Airline {offer_id}",
    )
    return FlightOption(
        provider="swoop",
        provider_offer_id=offer_id,
        origin_code="KIX",
        destination_code="DAC",
        adults=2,
        total_duration_minutes=480,
        stops=0,
        total_price=price,
        currency="USD",
        price_type="shopping_total",
        airline_names=[f"Airline {offer_id}"],
        slices=[
            FlightSlice(
                origin_code="KIX",
                destination_code="DAC",
                departure_at=departure,
                arrival_at=arrival,
                duration_minutes=480,
                stops=0,
                segments=[segment],
            )
        ],
        fetched_at=FETCHED_AT,
    )


def _hotel(
    city: str,
    day_offset: int,
    option_suffix: str,
    price: float,
    *,
    currency: str = "USD",
) -> HotelOption:
    check_in = START_DATE + timedelta(days=day_offset)
    check_out = check_in + timedelta(days=1)
    return HotelOption(
        provider="liteapi",
        provider_hotel_id=f"{city.casefold()}-{option_suffix}",
        provider_offer_id=f"{city.casefold()}-{option_suffix}",
        stay_key=build_hotel_stay_key(city, check_in, check_out),
        name=f"{city} Hotel {option_suffix.upper()}",
        city=city,
        check_in=check_in,
        check_out=check_out,
        nights=1,
        total_price=price,
        currency=currency,
        fetched_at=FETCHED_AT,
    )


def _plan(*, user_budget: float | None = 2300) -> TripPlan:
    hotels = []
    for index, (city, price) in enumerate(zip(CITIES, HOTEL_PRICES)):
        hotels.extend(
            [
                _hotel(city, index, "a", price),
                _hotel(city, index, "b", price + 60),
            ]
        )
    return TripPlan(
        title="Japan plan",
        origin="Bangladesh",
        destination="Japan",
        start_date=START_DATE,
        end_date=START_DATE + timedelta(days=3),
        duration_days=3,
        travelers=2,
        preferences=[],
        days=[
            ItineraryDay(
                day_number=index + 1,
                date=START_DATE + timedelta(days=index),
                city=city,
                activities=[Activity(name=f"{city} activity", category="culture")],
            )
            for index, city in enumerate(CITIES)
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Local trip costs", amount_usd=950)],
            estimated_total_usd=950,
            user_budget_usd=user_budget,
        ),
        recommendations=TravelRecommendations(
            flights=[_flight("flight-a", 650), _flight("flight-b", 720)],
            hotels=hotels,
            flight_status=RecommendationDomainState(
                status="available",
                provider_result_count=2,
            ),
            hotel_status=RecommendationDomainState(
                status="available",
                provider_result_count=6,
            ),
        ),
        practical_notes=[],
    )


def _selections(
    *,
    flight_id: str = "flight-a",
    hotel_suffixes: tuple[str, str, str] = ("a", "a", "a"),
) -> TravelSelections:
    hotels = [
        _hotel(city, index, suffix, HOTEL_PRICES[index] + (60 if suffix == "b" else 0))
        for index, (city, suffix) in enumerate(zip(CITIES, hotel_suffixes))
    ]
    return TravelSelections(
        selected_flight_id=flight_id,
        selected_hotels=[
            SelectedHotelStay(
                stay_key=hotel.stay_key,
                hotel_option_id=hotel.provider_offer_id,
            )
            for hotel in hotels
        ],
    )


def _request(**kwargs) -> TravelSelectionRequest:
    selections = _selections(**kwargs)
    return TravelSelectionRequest(
        thread_id="thread-a",
        **selections.model_dump(),
    )


def _split_plan() -> TripPlan:
    plan = _plan()
    assert plan.recommendations is not None
    plan.recommendations.flights = []
    plan.recommendations.outbound_flights = [
        _flight("outbound-a", 650),
        _flight("outbound-b", 720),
    ]
    plan.recommendations.return_flights = [
        _return_flight("return-a", 510),
        _return_flight("return-b", 590),
    ]
    plan.recommendations.outbound_flight_status = RecommendationDomainState(
        status="available",
        provider_result_count=2,
    )
    plan.recommendations.return_flight_status = RecommendationDomainState(
        status="available",
        provider_result_count=2,
    )
    return plan


def test_complete_multi_city_selection_calculates_expected_decimal_summary():
    plan = _plan()
    original_budget = plan.budget.model_copy(deep=True)
    original_recommendations = plan.recommendations.model_copy(deep=True)

    summary = calculate_trip_cost_summary(plan, _selections())

    assert summary.base_trip_total_usd == 950
    assert summary.selected_flight_usd == 650
    assert summary.selected_hotels_usd == 920
    assert summary.additions_total_usd == 1570
    assert summary.updated_trip_total_usd == 2520
    assert summary.user_budget_usd == 2300
    assert summary.difference_from_budget_usd == 220
    assert plan.budget == original_budget
    assert plan.recommendations == original_recommendations


def test_separate_outbound_and_return_prices_are_combined_authoritatively():
    hotels = _selections().selected_hotels
    selections = TravelSelections(
        selected_outbound_flight_id="outbound-a",
        selected_return_flight_id="return-a",
        selected_hotels=hotels,
    )

    summary = calculate_trip_cost_summary(_split_plan(), selections)

    assert summary.selected_flight_usd == 1160
    assert summary.selected_hotels_usd == 920
    assert summary.updated_trip_total_usd == 3030


def test_split_flight_request_rejects_partial_or_mixed_leg_selection():
    hotels = _selections().selected_hotels
    with pytest.raises(ValidationError, match="both outbound and return"):
        TravelSelectionRequest(
            thread_id="thread-a",
            selected_outbound_flight_id="outbound-a",
            selected_hotels=hotels,
        )
    with pytest.raises(ValidationError, match="either one bundled flight"):
        TravelSelectionRequest(
            thread_id="thread-a",
            selected_flight_id="legacy",
            selected_outbound_flight_id="outbound-a",
            selected_return_flight_id="return-a",
            selected_hotels=hotels,
        )


def test_markdown_renders_selected_travel_and_updated_cost_separately():
    plan = _plan()
    selections = _selections()
    summary = calculate_trip_cost_summary(plan, selections)

    rendered = render_itinerary(
        plan,
        travel_selections=selections,
        trip_cost_summary=summary,
    )

    assert "## Base Trip Estimate" in rendered
    assert "**Base trip estimate:** $950" in rendered
    assert "## Selected Travel" in rendered
    assert "Selected flight: Airline flight-a" in rendered
    assert "Selected hotel · Tokyo" in rendered
    assert "## Updated Trip Cost" in rendered
    assert "**Updated Trip Total:** $2,520" in rendered
    assert "$220 is the extra money needed for flight and hotel" in rendered
    assert "Original Target Budget" not in rendered
    assert "reservation or purchase" in rendered


def test_under_budget_and_missing_budget_comparisons_are_correct():
    under = calculate_trip_cost_summary(_plan(user_budget=3000), _selections())
    no_target = calculate_trip_cost_summary(_plan(user_budget=None), _selections())

    assert under.difference_from_budget_usd == -480
    assert no_target.user_budget_usd is None
    assert no_target.difference_from_budget_usd is None
    assert no_target.updated_trip_total_usd == 2520


def test_provider_totals_are_not_multiplied_by_travelers_or_nights():
    plan = _plan()
    plan.recommendations.flights[0].total_price = 714.20
    plan.recommendations.hotels[0].total_price = 480

    summary = calculate_trip_cost_summary(plan, _selections())

    assert summary.selected_flight_usd == 714.20
    assert summary.selected_hotels_usd == 980


def test_unknown_flight_wrong_stay_missing_stay_and_duplicate_stay_are_atomic_errors():
    plan = _plan()
    with pytest.raises(TravelSelectionError, match="no longer available"):
        calculate_trip_cost_summary(plan, _selections(flight_id="flight-old"))

    selections = _selections()
    selections.selected_hotels[0].hotel_option_id = "kyoto-a"
    with pytest.raises(TravelSelectionError, match="no longer available"):
        calculate_trip_cost_summary(plan, selections)

    incomplete = _selections().model_copy(
        update={"selected_hotels": _selections().selected_hotels[:2]}
    )
    with pytest.raises(TravelSelectionError, match="every required stay"):
        calculate_trip_cost_summary(plan, incomplete)

    duplicate_data = _selections().model_dump()
    duplicate_data["selected_hotels"][1] = duplicate_data["selected_hotels"][0]
    with pytest.raises(ValidationError, match="one hotel"):
        TravelSelections.model_validate(duplicate_data)


def test_request_rejects_malformed_stay_key_and_client_prices():
    payload = _request().model_dump()
    payload["selected_hotels"][0]["stay_key"] = "Tokyo"
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        TravelSelectionRequest.model_validate(payload)

    payload = _request().model_dump()
    payload["flight_price"] = 1
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        TravelSelectionRequest.model_validate(payload)

    payload = _request().model_dump()
    payload["selected_hotels"][0]["price"] = 1
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        TravelSelectionRequest.model_validate(payload)


def test_mixed_currency_selection_is_not_calculated():
    plan = _plan()
    hotel = plan.recommendations.hotels[0]
    plan.recommendations.hotels[0] = hotel.model_copy(update={"currency": "EUR"})

    with pytest.raises(TravelSelectionError, match="not priced in USD"):
        calculate_trip_cost_summary(plan, _selections())


class FakeGraph:
    def __init__(self, states):
        self.states = states
        self.updates = []

    async def aget_state(self, config):
        thread_id = config["configurable"]["thread_id"]
        values = self.states.get(thread_id)
        return SimpleNamespace(
            values=values or {},
            created_at="2026-08-21T00:00:00Z" if values is not None else None,
        )

    async def aupdate_state(self, config, values, *, as_node):
        thread_id = config["configurable"]["thread_id"]
        self.updates.append((thread_id, values, as_node))
        self.states[thread_id].update(values)


def test_confirmation_uses_checkpoint_snapshot_and_makes_zero_provider_calls(
    monkeypatch,
):
    calls = {"swoop": 0, "liteapi": 0}

    async def fail_swoop(*args, **kwargs):
        calls["swoop"] += 1
        raise AssertionError("Swoop must not run during selection")

    async def fail_liteapi(*args, **kwargs):
        calls["liteapi"] += 1
        raise AssertionError("LiteAPI must not run during selection")

    monkeypatch.setattr(SwoopFlightProvider, "search_flights", fail_swoop)
    monkeypatch.setattr(LiteApiHotelProvider, "search_hotels", fail_liteapi)
    states = {
        "thread-a": {
            "itinerary": _plan(),
            "detailed_routing_plan": {"stale": True},
        }
    }
    graph = FakeGraph(states)

    async def get_fake_graph():
        return graph

    monkeypatch.setattr(
        TravelSelectionService,
        "_get_graph",
        staticmethod(get_fake_graph),
    )

    response = asyncio.run(TravelSelectionService().confirm(_request()))

    assert calls == {"swoop": 0, "liteapi": 0}
    assert response.trip_cost_summary.updated_trip_total_usd == 2520
    assert states["thread-a"]["travel_selections"] == _selections()
    assert states["thread-a"]["detailed_routing_plan"] is None
    assert graph.updates[0][2] == "memory_write"
    assert set(graph.updates[0][1]) == {
        "travel_selections",
        "trip_cost_summary",
        "detailed_routing_plan",
        "confirmed_snapshot",
    }
    assert response.confirmed_snapshot.revision == 1
    assert response.confirmed_snapshot.cost_summary == response.trip_cost_summary


def test_invalid_complete_set_does_not_partially_mutate_checkpoint(monkeypatch):
    existing = _selections(flight_id="flight-a")
    states = {
        "thread-a": {
            "itinerary": _plan(),
            "travel_selections": existing,
            "trip_cost_summary": calculate_trip_cost_summary(_plan(), existing),
        }
    }
    graph = FakeGraph(states)

    async def get_fake_graph():
        return graph

    monkeypatch.setattr(
        TravelSelectionService,
        "_get_graph",
        staticmethod(get_fake_graph),
    )

    with pytest.raises(TravelSelectionError):
        asyncio.run(
            TravelSelectionService().confirm(_request(flight_id="flight-old"))
        )

    assert states["thread-a"]["travel_selections"] == existing
    assert graph.updates == []


def test_change_selection_replaces_old_cost_without_provider_refresh(monkeypatch):
    states = {"thread-a": {"itinerary": _plan()}}
    graph = FakeGraph(states)

    async def get_fake_graph():
        return graph

    monkeypatch.setattr(
        TravelSelectionService,
        "_get_graph",
        staticmethod(get_fake_graph),
    )
    service = TravelSelectionService()

    first = asyncio.run(service.confirm(_request()))
    changed = asyncio.run(
        service.confirm(
            _request(flight_id="flight-b", hotel_suffixes=("b", "a", "a"))
        )
    )

    assert first.trip_cost_summary.updated_trip_total_usd == 2520
    assert changed.trip_cost_summary.selected_flight_usd == 720
    assert changed.trip_cost_summary.selected_hotels_usd == 980
    assert changed.trip_cost_summary.updated_trip_total_usd == 2650
    assert states["thread-a"]["travel_selections"].selected_flight_id == "flight-b"


def test_return_leg_replacement_recalculates_cost_and_requests_new_routing(
    monkeypatch,
):
    hotels = _selections().selected_hotels
    initial_request = TravelSelectionRequest(
        thread_id="thread-a",
        selected_outbound_flight_id="outbound-a",
        selected_return_flight_id="return-a",
        selected_hotels=hotels,
    )
    states = {"thread-a": {"itinerary": _split_plan()}}
    graph = FakeGraph(states)

    async def get_fake_graph():
        return graph

    monkeypatch.setattr(
        TravelSelectionService,
        "_get_graph",
        staticmethod(get_fake_graph),
    )
    monkeypatch.setattr(
        FlightLegSelectionService,
        "_get_graph",
        staticmethod(get_fake_graph),
    )
    first = asyncio.run(TravelSelectionService().confirm(initial_request))
    routing_plan = DetailedRoutingPlan(
        days=[DetailedRoutingDay(day_number=1, date=START_DATE)],
        generated_at=FETCHED_AT,
        has_ai_estimates=False,
    )
    routing_calls = []

    async def fake_generate(self, request):
        routing_calls.append(request.thread_id)
        return SimpleNamespace(detailed_routing_plan=routing_plan)

    monkeypatch.setattr(DetailedRoutingService, "generate", fake_generate)

    changed = asyncio.run(
        FlightLegSelectionService().confirm(
            FlightLegSelectionRequest(
                thread_id="thread-a",
                scope="return",
                selected_flight_id="return-b",
            )
        )
    )

    assert first.confirmed_snapshot.revision == 1
    assert changed.travel_selections.selected_outbound_flight_id == "outbound-a"
    assert changed.travel_selections.selected_return_flight_id == "return-b"
    assert changed.trip_cost_summary.selected_flight_usd == 1240
    assert changed.trip_cost_summary.updated_trip_total_usd == 3110
    assert changed.confirmed_snapshot.revision == 2
    assert changed.confirmed_snapshot.routing_plan == routing_plan
    assert routing_calls == ["thread-a"]


def test_unknown_thread_and_missing_itinerary_are_deterministic_client_errors(
    monkeypatch,
):
    graph = FakeGraph({"empty": {"trip": None}})

    async def get_fake_graph():
        return graph

    monkeypatch.setattr(
        TravelSelectionService,
        "_get_graph",
        staticmethod(get_fake_graph),
    )
    service = TravelSelectionService()
    unknown_request = _request().model_copy(update={"thread_id": "unknown"})
    empty_request = _request().model_copy(update={"thread_id": "empty"})

    with pytest.raises(TravelSelectionError) as unknown:
        asyncio.run(service.confirm(unknown_request))
    with pytest.raises(TravelSelectionError) as empty:
        asyncio.run(service.confirm(empty_request))

    assert unknown.value.status_code == 404
    assert empty.value.status_code == 409
