import asyncio
from datetime import UTC, date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    FlightOption,
    FlightSegment,
    FlightSlice,
    HotelOption,
    ItineraryDay,
    RecommendationDomainState,
    ResolvedPlace,
    RouteTimeEstimate,
    SelectedHotelStay,
    TravelRecommendations,
    TravelSelections,
    TripCostSummary,
    TripPlan,
    build_hotel_stay_key,
)
from app.schemas.api import DetailedRoutingRequest
from app.services.detailed_routing import (
    DetailedRoutingError,
    DetailedRoutingService,
)
from app.services.detailed_routing_context import (
    DetailedRoutingContextError,
    RequiredRouteLeg,
    RoutingPoint,
    build_detailed_routing_context,
    collect_required_route_legs,
    with_resolved_point,
)
from app.services.detailed_routing_estimates import (
    ActivityVisitEstimate,
    DetailedRoutingPlanningEstimates,
    LlmRouteEstimate,
    build_planning_estimates,
)
from app.services.detailed_timetable import build_detailed_timetable
from app.services.itinerary_renderer import render_itinerary
from app.services.recommendations.flights import SwoopFlightProvider
from app.services.recommendations.hotels import LiteApiHotelProvider
from app.services.routing import RouteResult
from app.services.travel_selection import calculate_trip_cost_summary

JST = timezone(timedelta(hours=9))
START = date(2026, 9, 10)
FETCHED_AT = datetime(2026, 8, 21, tzinfo=UTC)


def _segment(origin, destination, departure, arrival):
    return FlightSegment(
        origin_code=origin,
        destination_code=destination,
        departure_at=departure,
        arrival_at=arrival,
        duration_minutes=int((arrival - departure).total_seconds() / 60),
    )


def _flight() -> FlightOption:
    outbound_departure = datetime(2026, 9, 10, 5, 20, tzinfo=JST)
    outbound_arrival = datetime(2026, 9, 10, 10, 20, tzinfo=JST)
    return_departure = datetime(2026, 9, 12, 20, 30, tzinfo=JST)
    return_arrival = datetime(2026, 9, 13, 2, 30, tzinfo=JST)
    outbound_segment = _segment(
        "DAC", "NRT", outbound_departure, outbound_arrival
    )
    return_segment = _segment("KIX", "DAC", return_departure, return_arrival)
    return FlightOption(
        provider="swoop",
        provider_offer_id="flight-open-jaw",
        origin_code="DAC",
        destination_code="NRT",
        adults=2,
        total_duration_minutes=660,
        stops=0,
        total_price=700,
        currency="USD",
        price_type="shopping_total",
        slices=[
            FlightSlice(
                origin_code="DAC",
                destination_code="NRT",
                departure_at=outbound_departure,
                arrival_at=outbound_arrival,
                duration_minutes=300,
                stops=0,
                segments=[outbound_segment],
            ),
            FlightSlice(
                origin_code="KIX",
                destination_code="DAC",
                departure_at=return_departure,
                arrival_at=return_arrival,
                duration_minutes=360,
                stops=0,
                segments=[return_segment],
            ),
        ],
        fetched_at=FETCHED_AT,
    )


def _hotel(city, check_in, check_out, latitude, longitude):
    stay_key = build_hotel_stay_key(city, check_in, check_out)
    return HotelOption(
        provider="liteapi",
        provider_hotel_id=f"{city}-hotel",
        provider_offer_id=f"{city}-offer",
        stay_key=stay_key,
        name=f"Hotel {city}",
        city=city,
        country="Japan",
        latitude=latitude,
        longitude=longitude,
        check_in=check_in,
        check_out=check_out,
        nights=(check_out - check_in).days,
        total_price=300,
        currency="USD",
        fetched_at=FETCHED_AT,
    )


def _activity(name, latitude, longitude, *, start_time=None):
    place = ResolvedPlace(
        provider="geoapify",
        provider_place_id=name.casefold().replace(" ", "-"),
        name=name,
        city="Tokyo",
        country="Japan",
        latitude=latitude,
        longitude=longitude,
        resolution_status="resolved",
    )
    return Activity(
        name=name,
        category="culture",
        start_time=start_time,
        place=place,
        place_resolution_status="resolved",
        travel_mode_to_next="transit",
    )


def _plan(*, final_activity_start=None) -> TripPlan:
    tokyo = _hotel("Tokyo", START, START + timedelta(days=1), 35.69, 139.70)
    kyoto = _hotel(
        "Kyoto",
        START + timedelta(days=1),
        START + timedelta(days=2),
        35.01,
        135.76,
    )
    return TripPlan(
        title="Japan route plan",
        origin="Bangladesh",
        destination="Japan",
        start_date=START,
        end_date=START + timedelta(days=2),
        duration_days=3,
        travelers=2,
        preferences=[],
        days=[
            ItineraryDay(
                day_number=1,
                date=START,
                city="Tokyo",
                activities=[_activity("Meiji Shrine", 35.676, 139.699)],
            ),
            ItineraryDay(
                day_number=2,
                date=START + timedelta(days=1),
                city="Kyoto",
                activities=[
                    _activity("Fushimi Inari", 34.967, 135.772),
                    _activity("Kiyomizu-dera", 34.994, 135.785),
                ],
            ),
            ItineraryDay(
                day_number=3,
                date=START + timedelta(days=2),
                city="Kyoto",
                activities=[
                    _activity(
                        "Nishiki Market",
                        35.005,
                        135.765,
                        start_time=final_activity_start,
                    )
                ],
            ),
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Local costs", amount_usd=800)],
            estimated_total_usd=800,
            user_budget_usd=2000,
        ),
        recommendations=TravelRecommendations(
            flights=[_flight()],
            hotels=[tokyo, kyoto],
            flight_status=RecommendationDomainState(
                status="available", provider_result_count=1
            ),
            hotel_status=RecommendationDomainState(
                status="available", provider_result_count=2
            ),
        ),
        practical_notes=[],
    )


def _selections(plan=None):
    selected_plan = plan or _plan()
    hotels = selected_plan.recommendations.hotels
    return TravelSelections(
        selected_flight_id="flight-open-jaw",
        selected_hotels=[
            SelectedHotelStay(
                stay_key=hotel.stay_key,
                hotel_option_id=hotel.provider_offer_id,
            )
            for hotel in hotels
        ],
    )


def _context_with_airports(plan=None):
    selected_plan = plan or _plan()
    context = build_detailed_routing_context(
        selected_plan,
        _selections(selected_plan),
    )
    context = with_resolved_point(
        context,
        stop_id="arrival-airport",
        latitude=35.77,
        longitude=140.39,
    )
    return with_resolved_point(
        context,
        stop_id="departure-airport",
        latitude=34.43,
        longitude=135.24,
    )


class FakeRoutingProvider:
    def __init__(self, minutes=25, failures=None):
        self.minutes = minutes
        self.failures = failures or set()
        self.calls = []

    async def get_route(self, **kwargs):
        self.calls.append(kwargs)
        key = (
            round(kwargs["origin_latitude"], 3),
            round(kwargs["destination_latitude"], 3),
        )
        if key in self.failures:
            return None
        return RouteResult(
            distance_meters=4200,
            duration_seconds=self.minutes * 60,
        )


class FakeEstimator:
    def __init__(self, *, invalid_route=False, fail=False, visit_minutes=60):
        self.calls = []
        self.invalid_route = invalid_route
        self.fail = fail
        self.visit_minutes = visit_minutes

    async def estimate(self, *, missing_routes, activities):
        self.calls.append((missing_routes, activities))
        if self.fail:
            raise RuntimeError("LLM unavailable")
        route_estimates = [
            LlmRouteEstimate(
                leg_id=item["leg_id"],
                minimum_minutes=50 if self.invalid_route else 20,
                maximum_minutes=20 if self.invalid_route else 35,
                brief_reason="Conservative city transit planning range.",
            )
            for item in missing_routes
        ]
        return DetailedRoutingPlanningEstimates(
            route_estimates=route_estimates,
            activity_estimates=[
                ActivityVisitEstimate(
                    activity_id=item["activity_id"],
                    minimum_minutes=self.visit_minutes,
                    maximum_minutes=self.visit_minutes,
                    brief_reason="Suggested visit duration.",
                )
                for item in activities
            ],
        )


def test_context_reuses_open_jaw_flight_and_maps_multi_city_hotels():
    plan = _plan()
    context = build_detailed_routing_context(plan, _selections(plan))

    assert context.arrival.airport_code == "NRT"
    assert context.arrival.local_time.hour == 10
    assert context.departure.airport_code == "KIX"
    assert context.departure.local_time.hour == 20
    assert [day.hotel.name for day in context.days] == [
        "Hotel Tokyo",
        "Hotel Kyoto",
        "Hotel Kyoto",
    ]


def test_context_rejects_incomplete_multi_city_hotel_selection():
    plan = _plan()
    selections = _selections(plan).model_copy(
        update={"selected_hotels": _selections(plan).selected_hotels[:1]}
    )

    with pytest.raises(DetailedRoutingContextError, match="every required stay"):
        build_detailed_routing_context(plan, selections)


def test_thread_only_request_rejects_client_supplied_route_or_selection_facts():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DetailedRoutingRequest.model_validate(
            {
                "thread_id": "thread-a",
                "airport_code": "HND",
                "selected_flight_id": "replacement-flight",
            }
        )


def test_geoapify_success_is_exact_and_skips_llm_route_fallback():
    context = _context_with_airports()
    required = collect_required_route_legs(context)
    estimator = FakeEstimator()
    provider = FakeRoutingProvider(minutes=25)

    bundle = asyncio.run(
        build_planning_estimates(
            context,
            required,
            routing_provider=provider,
            planning_estimator=estimator,
        )
    )

    provider_leg = next(
        leg for leg in bundle.route_legs.values() if leg.duration.source == "geoapify"
    )
    assert provider_leg.duration == RouteTimeEstimate(
        min_minutes=25,
        max_minutes=25,
        planning_minutes=25,
        source="geoapify",
    )
    assert provider_leg.distance_km == 4.2
    assert estimator.calls[0][0] == []
    assert len(estimator.calls) == 1


def test_geoapify_duration_above_planning_limit_uses_llm_fallback():
    context = _context_with_airports()
    required = collect_required_route_legs(context)
    estimator = FakeEstimator()

    bundle = asyncio.run(
        build_planning_estimates(
            context,
            required,
            routing_provider=FakeRoutingProvider(minutes=572),
            planning_estimator=estimator,
        )
    )

    assert len(estimator.calls) == 1
    assert len(estimator.calls[0][0]) == len(required)
    assert all(
        leg.duration.source == "llm_estimate"
        and leg.duration.planning_minutes == 35
        for leg in bundle.route_legs.values()
    )
    assert bundle.geoapify_success_count == 0
    assert bundle.geoapify_failure_count == len(required)


def test_failed_routes_and_all_activity_estimates_use_one_llm_batch():
    context = _context_with_airports()
    required = collect_required_route_legs(context)
    estimator = FakeEstimator(visit_minutes=90)

    bundle = asyncio.run(
        build_planning_estimates(
            context,
            required,
            routing_provider=None,
            planning_estimator=estimator,
        )
    )

    assert len(estimator.calls) == 1
    assert len(estimator.calls[0][0]) == len(required)
    assert len(estimator.calls[0][1]) == 4
    assert all(
        leg.duration.source == "llm_estimate"
        and leg.duration.planning_minutes == 35
        and leg.duration.approximate
        for leg in bundle.route_legs.values()
    )
    assert all(value.planning_minutes == 90 for value in bundle.visit_durations.values())


def test_duplicate_provider_routes_are_deduplicated_within_request():
    context = _context_with_airports()
    original = collect_required_route_legs(context)[0]
    duplicate = RequiredRouteLeg(
        leg_id="duplicate-leg",
        day_number=original.day_number,
        origin=original.origin,
        destination=original.destination,
        requested_mode=original.requested_mode,
    )
    provider = FakeRoutingProvider(minutes=18)

    bundle = asyncio.run(
        build_planning_estimates(
            context,
            [original, duplicate],
            routing_provider=provider,
            planning_estimator=None,
        )
    )

    assert len(provider.calls) == 1
    assert bundle.route_legs[original.leg_id].duration.source == "geoapify"
    assert bundle.route_legs[duplicate.leg_id].duration.source == "geoapify"


def test_partial_provider_failure_falls_back_only_for_failed_leg():
    context = _context_with_airports()
    required = collect_required_route_legs(context)
    failed = required[0]
    provider = FakeRoutingProvider(
        minutes=22,
        failures={
            (
                round(failed.origin.latitude, 3),
                round(failed.destination.latitude, 3),
            )
        },
    )

    bundle = asyncio.run(
        build_planning_estimates(
            context,
            required,
            routing_provider=provider,
            planning_estimator=FakeEstimator(),
        )
    )

    assert bundle.route_legs[failed.leg_id].duration.source == "llm_estimate"
    assert any(
        leg.duration.source == "geoapify"
        for leg_id, leg in bundle.route_legs.items()
        if leg_id != failed.leg_id
    )


def test_provider_and_llm_failure_remain_graceful_and_use_visit_policy():
    context = _context_with_airports()
    required = collect_required_route_legs(context)

    bundle = asyncio.run(
        build_planning_estimates(
            context,
            required,
            routing_provider=None,
            planning_estimator=FakeEstimator(fail=True),
        )
    )

    assert all(
        leg.duration.source == "unavailable" for leg in bundle.route_legs.values()
    )
    assert all(
        visit.source == "planning_policy" and visit.planning_minutes == 60
        for visit in bundle.visit_durations.values()
    )


def test_invalid_llm_route_range_is_rejected_without_crashing():
    context = build_detailed_routing_context(_plan(), _selections())
    required = collect_required_route_legs(context)
    bundle = asyncio.run(
        build_planning_estimates(
            context,
            required,
            routing_provider=None,
            planning_estimator=FakeEstimator(invalid_route=True),
        )
    )

    assert all(
        leg.duration.source == "unavailable" for leg in bundle.route_legs.values()
    )


def test_llm_output_schema_cannot_contain_invented_schedule_fields():
    route_properties = LlmRouteEstimate.model_json_schema()["properties"]
    assert set(route_properties) == {
        "leg_id",
        "minimum_minutes",
        "maximum_minutes",
        "brief_reason",
    }
    assert not {"train_number", "station", "line_name", "departure_schedule"} & set(
        route_properties
    )


def test_arrival_and_normal_day_clock_arithmetic_is_python_owned():
    context = build_detailed_routing_context(_plan(), _selections())
    required = collect_required_route_legs(context)
    bundle = asyncio.run(
        build_planning_estimates(
            context,
            required,
            routing_provider=FakeRoutingProvider(minutes=20),
            planning_estimator=FakeEstimator(visit_minutes=60),
        )
    )
    detailed = build_detailed_timetable(context, bundle)

    arrival_buffer = next(
        stop for stop in detailed.days[0].stops if stop.stop_id == "arrival-processing"
    )
    assert arrival_buffer.arrival_time.hour == 10
    assert arrival_buffer.arrival_time.minute == 20
    assert arrival_buffer.departure_time.hour == 11
    assert arrival_buffer.departure_time.minute == 50
    day_two_activities = [
        stop for stop in detailed.days[1].stops if stop.stop_type == "activity"
    ]
    assert [(stop.arrival_time.strftime("%H:%M"), stop.departure_time.strftime("%H:%M")) for stop in day_two_activities] == [
        ("09:20", "10:20"),
        ("10:40", "11:40"),
    ]


def test_return_flight_creates_hard_airport_deadline():
    context = _context_with_airports()
    required = collect_required_route_legs(context)
    bundle = asyncio.run(
        build_planning_estimates(
            context,
            required,
            routing_provider=FakeRoutingProvider(minutes=70),
            planning_estimator=FakeEstimator(visit_minutes=60),
        )
    )
    detailed = build_detailed_timetable(context, bundle)

    assert detailed.days[-1].latest_departure_for_airport.strftime("%H:%M") == "16:20"
    hotel_departure_buffer = next(
        stop
        for stop in detailed.days[-1].stops
        if stop.stop_id == "hotel-departure-buffer"
    )
    assert hotel_departure_buffer.arrival_time.strftime("%H:%M") == "16:05"
    assert hotel_departure_buffer.departure_time.strftime("%H:%M") == "16:20"
    assert hotel_departure_buffer.source == "planning_policy"
    flight = next(
        stop for stop in detailed.days[-1].stops if stop.stop_id == "departure-flight"
    )
    assert flight.departure_time.strftime("%H:%M") == "20:30"


def test_final_activity_that_does_not_fit_is_not_compressed_or_removed_from_plan():
    plan = _plan(final_activity_start="16:00")
    context = _context_with_airports(plan)
    required = collect_required_route_legs(context)
    bundle = asyncio.run(
        build_planning_estimates(
            context,
            required,
            routing_provider=FakeRoutingProvider(minutes=70),
            planning_estimator=FakeEstimator(visit_minutes=90),
        )
    )
    detailed = build_detailed_timetable(context, bundle)
    final_activity = next(
        stop for stop in detailed.days[-1].stops if stop.stop_type == "activity"
    )

    assert final_activity.scheduled is False
    assert final_activity.planned_visit_minutes == 90
    assert "could not fit" in detailed.days[-1].warnings[0]
    assert plan.days[-1].activities[0].name == "Nishiki Market"


def test_detailed_plan_markdown_labels_facts_estimates_and_buffers():
    plan = _plan()
    context = _context_with_airports(plan)
    bundle = asyncio.run(
        build_planning_estimates(
            context,
            collect_required_route_legs(context),
            routing_provider=None,
            planning_estimator=FakeEstimator(),
        )
    )
    detailed = build_detailed_timetable(context, bundle)

    rendered = render_itinerary(plan, detailed_routing_plan=detailed)

    assert "## Detailed Routing & Timetable" in rendered
    assert "Selected flight fact" in rendered
    assert "AI planning estimate" in rendered
    assert "Planning buffer" in rendered
    assert "not a live transit schedule" in rendered


class FakeGraph:
    def __init__(self, values):
        self.values = values
        self.updates = []

    async def aget_state(self, config):
        return SimpleNamespace(values=self.values, created_at="now")

    async def aupdate_state(self, config, values, *, as_node):
        self.updates.append((values, as_node))
        self.values.update(values)


def test_service_persists_complete_plan_and_reuses_snapshot_without_search(monkeypatch):
    plan = _plan()
    selections = _selections(plan)
    graph = FakeGraph(
        {
            "itinerary": plan,
            "travel_selections": selections,
            "trip_cost_summary": calculate_trip_cost_summary(plan, selections),
        }
    )
    provider = FakeRoutingProvider(minutes=25)
    estimator = FakeEstimator()
    search_calls = {"swoop": 0, "liteapi": 0}

    async def fail_swoop(*args, **kwargs):
        search_calls["swoop"] += 1
        raise AssertionError("Detailed routing must not search flights")

    async def fail_liteapi(*args, **kwargs):
        search_calls["liteapi"] += 1
        raise AssertionError("Detailed routing must not search hotels")

    monkeypatch.setattr(SwoopFlightProvider, "search_flights", fail_swoop)
    monkeypatch.setattr(LiteApiHotelProvider, "search_hotels", fail_liteapi)

    async def get_graph():
        return graph

    monkeypatch.setattr(DetailedRoutingService, "_get_graph", staticmethod(get_graph))
    monkeypatch.setattr(
        DetailedRoutingService,
        "_build_routing_provider",
        staticmethod(lambda key: provider),
    )
    monkeypatch.setattr(
        DetailedRoutingService,
        "_build_planning_estimator",
        staticmethod(lambda: estimator),
    )
    monkeypatch.setattr(
        DetailedRoutingService,
        "_build_places_provider",
        staticmethod(lambda key: None),
    )

    response = asyncio.run(
        DetailedRoutingService().generate(DetailedRoutingRequest(thread_id="thread-a"))
    )

    assert response.detailed_routing_plan.days
    assert graph.updates[0][1] == "memory_write"
    assert set(graph.updates[0][0]) == {"detailed_routing_plan"}
    assert plan.budget.estimated_total_usd == 800
    assert graph.values["travel_selections"] == selections
    assert graph.values["detailed_routing_plan"] == response.detailed_routing_plan
    assert search_calls == {"swoop": 0, "liteapi": 0}


def test_service_rejects_missing_selection_before_any_provider(monkeypatch):
    graph = FakeGraph({"itinerary": _plan()})
    calls = {"provider": 0}

    async def get_graph():
        return graph

    def provider(key):
        calls["provider"] += 1
        raise AssertionError("Provider must not be constructed")

    monkeypatch.setattr(DetailedRoutingService, "_get_graph", staticmethod(get_graph))
    monkeypatch.setattr(
        DetailedRoutingService,
        "_build_routing_provider",
        staticmethod(provider),
    )

    with pytest.raises(DetailedRoutingError) as error:
        asyncio.run(
            DetailedRoutingService().generate(
                DetailedRoutingRequest(thread_id="thread-a")
            )
        )

    assert error.value.status_code == 409
    assert calls == {"provider": 0}
    assert graph.updates == []
