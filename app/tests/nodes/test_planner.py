from datetime import date

import pytest
from langchain_core.messages import HumanMessage

from app.graph.nodes.planner import (
    _classify_flight_search_scope,
    _classify_turn,
    planner_node,
    planner_router,
)
from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    ItineraryDay,
    TripPlan,
)


def _plan() -> TripPlan:
    return TripPlan(
        title="Japan plan",
        origin="Dhaka",
        destination="Japan",
        start_date=date(2026, 9, 10),
        end_date=date(2026, 9, 15),
        duration_days=6,
        travelers=2,
        preferences=[],
        days=[
            ItineraryDay(
                day_number=1,
                city="Tokyo",
                activities=[Activity(name="Arrival", category="transport")],
            )
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Local costs", amount_usd=500)],
            estimated_total_usd=500,
        ),
        practical_notes=[],
    )


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Can you suggest me departure flights?", "outbound"),
        ("Show outbound flight options", "outbound"),
        ("Find a return flight", "return"),
        ("We want return flight suggestions", "return"),
        ("Recommend departure and return flights", "round_trip"),
        ("Show round-trip airfare", "round_trip"),
        ("Can you suggest flights?", "round_trip"),
        ("Show me flight recommendations", "round_trip"),
        ("I need a flight", "round_trip"),
        ("Add an airport transfer to the itinerary", None),
        ("I prefer fewer flights of stairs", None),
    ],
)
def test_classifies_explicit_flight_shopping_scope(message, expected):
    assert _classify_flight_search_scope(message) == expected


def test_contextual_departure_request_routes_around_itinerary_generation():
    result = planner_node(
        {
            "messages": [HumanMessage(content="Suggest departure flights")],
            "itinerary": _plan(),
        },
        config={},
    )
    state = {"itinerary": _plan(), **result}

    assert result["planner"]["next_action"] == "flight_search"
    assert result["turn_intent"] == "suggest_outbound_flights"
    assert result["flight_search_scope"] == "outbound"
    assert planner_router(state) == "flight_followup"


def test_non_flight_follow_up_uses_normal_trip_pipeline_and_resets_scope():
    result = planner_node(
        {
            "messages": [HumanMessage(content="Add more temples")],
            "itinerary": _plan(),
            "flight_search_scope": "outbound",
        },
        config={},
    )
    state = {"itinerary": _plan(), **result}

    assert result["planner"]["next_action"] == "plan_trip"
    assert result["turn_intent"] == "modify_trip"
    assert result["flight_search_scope"] is None
    assert planner_router(state) == "extractor"


def test_flight_request_without_existing_itinerary_uses_trip_collection():
    result = planner_node(
        {"messages": [HumanMessage(content="Suggest departure flights")]},
        config={},
    )

    assert result["planner"]["next_action"] == "flight_search"
    assert result["turn_intent"] == "suggest_outbound_flights"
    assert planner_router(result) == "flight_followup"


@pytest.mark.parametrize(
    "message",
    [
        "What currency is used in Japan?",
        "Is it safe to use the trains at night?",
        "Explain this hotel price.",
        "This is an unusual request that does not change anything.",
    ],
)
def test_questions_and_unknown_requests_default_to_answer_question(message):
    decision = _classify_turn(message, has_itinerary=True, config={})

    assert decision.intent == "answer_question"
    assert decision.changed_fields == []


@pytest.mark.parametrize(
    ("message", "intent", "route"),
    [
        ("Change my destination to Kyoto", "modify_trip", "extractor"),
        ("Replace temples with beaches", "modify_trip", "extractor"),
        ("Suggest hotels", "suggest_hotels", "hotel_followup"),
        (
            "Extend my travel plan two days more and suggest hotels",
            "extend_trip",
            "trip_extension",
        ),
    ],
)
def test_explicit_actions_get_dedicated_routes(message, intent, route):
    result = planner_node(
        {"messages": [HumanMessage(content=message)], "itinerary": _plan()},
        config={},
    )

    assert result["turn_intent"] == intent
    assert planner_router({"itinerary": _plan(), **result}) == route


def test_extension_extracts_relative_days_and_composite_hotel_action():
    decision = _classify_turn(
        "Extand my travel plan 2 days more, suggest hotel recommendations "
        "for the extra 2 days",
        has_itinerary=True,
        config={},
    )

    assert decision.intent == "extend_trip"
    assert decision.extension_days == 2
    assert decision.changed_fields == ["dates", "duration"]
    assert decision.refresh_hotels is True


def test_turn_decision_schema_is_strict_output_compatible():
    required = set(_classify_turn(
        "What currency is used?", has_itinerary=True, config={}
    ).model_json_schema()["required"])

    assert required == {
        "intent",
        "flight_scope",
        "extension_days",
        "changed_fields",
        "refresh_hotels",
    }


def test_compact_required_field_reply_continues_trip_collection():
    result = planner_node(
        {
            "messages": [HumanMessage(content="$2000 2")],
            "itinerary": None,
            "needs_clarification": True,
            "missing_fields": ["budget", "travelers"],
        },
        config={},
    )

    assert result["turn_intent"] == "create_trip"
    assert result["planner"]["next_action"] == "plan_trip"
    assert planner_router(result) == "extractor"


def test_question_during_clarification_remains_a_question():
    decision = _classify_turn(
        "Why do you need my budget?",
        has_itinerary=False,
        is_clarification_reply=True,
        config={},
    )

    assert decision.intent == "answer_question"
