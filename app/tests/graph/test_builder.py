import asyncio
from datetime import date, timedelta
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda

from app.graph import builder
from app.graph.nodes import agent, itinerary_generator, memory_recall, memory_write
from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    ItineraryDay,
    Trip,
    TripPlan,
)
from app.schemas.api import ChatRequest
from app.services.graph_services import GraphService


def test_graph_contains_structured_itinerary_and_memory_nodes():
    """Compiled graph exposes the structured generator and memory nodes."""

    graph = builder._build_graph()

    assert "memory_recall" in graph.nodes
    assert "memory_write" in graph.nodes
    assert "itinerary_generator" in graph.nodes
    assert "place_enrichment" in graph.nodes
    assert "image_enrichment" in graph.nodes
    assert "weather_enrichment" in graph.nodes
    assert "routing_enrichment" in graph.nodes
    assert "flight_recommendation" in graph.nodes
    assert "flight_followup" in graph.nodes
    assert "flight_responder" in graph.nodes
    assert "hotel_recommendation" in graph.nodes
    assert "hotel_followup" in graph.nodes
    assert "hotel_responder" in graph.nodes
    assert "question_responder" in graph.nodes
    assert "unsupported_responder" in graph.nodes
    assert "trip_extension" in graph.nodes
    assert "extension_generator" in graph.nodes
    assert "extension_merge" in graph.nodes
    edges = {
        (edge.source, edge.target)
        for edge in graph.get_graph().edges
        if not edge.conditional
    }
    assert ("itinerary_generator", "place_enrichment") in edges
    assert ("place_enrichment", "image_enrichment") in edges
    assert ("image_enrichment", "weather_enrichment") in edges
    assert ("weather_enrichment", "routing_enrichment") in edges
    assert ("routing_enrichment", "flight_recommendation") in edges
    conditional_edges = {
        (edge.source, edge.target)
        for edge in graph.get_graph().edges
        if edge.conditional
    }
    assert ("planner", "extractor") in conditional_edges
    assert ("planner", "flight_followup") in conditional_edges
    assert ("planner", "hotel_followup") in conditional_edges
    assert ("planner", "question_responder") in conditional_edges
    assert ("planner", "unsupported_responder") in conditional_edges
    assert ("planner", "trip_extension") in conditional_edges
    assert ("flight_recommendation", "hotel_recommendation") in edges
    assert ("flight_followup", "flight_responder") in edges
    assert ("flight_responder", "memory_write") in edges
    assert ("hotel_followup", "hotel_responder") in edges
    assert ("extension_generator", "extension_merge") in edges
    assert ("extension_routing", "extension_hotel") in edges
    assert ("hotel_recommendation", "responder") in edges


def test_build_input_includes_user_id():
    """Graph input carries the caller identity separately from thread_id."""

    request = ChatRequest(
        message="I am vegetarian.",
        thread_id="thread-123",
        user_id="user-123",
    )

    result = GraphService.build_input(request)

    assert result["user_id"] == "user-123"
    assert result["messages"][0].content == "I am vegetarian."
    assert result["selected_start_date"] is None
    assert result["selected_end_date"] is None


def test_build_input_includes_structured_date_selection():
    start_date = date.today() + timedelta(days=7)
    end_date = start_date + timedelta(days=4)
    request = ChatRequest(
        message="I selected my dates.",
        start_date=start_date,
        end_date=end_date,
    )

    result = GraphService.build_input(request)

    assert result["selected_start_date"] == start_date
    assert result["selected_end_date"] == end_date


def test_question_branch_preserves_itinerary_and_never_calls_extractor(monkeypatch):
    plan = TripPlan(
        title="Tokyo Plan",
        origin="Dhaka",
        destination="Japan",
        start_date=date(2026, 9, 10),
        end_date=date(2026, 9, 11),
        duration_days=2,
        travelers=1,
        preferences=[],
        days=[
            ItineraryDay(
                day_number=number,
                date=date(2026, 9, 9 + number),
                city="Tokyo",
                activities=[Activity(name="Explore Tokyo", category="visit")],
            )
            for number in (1, 2)
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Local costs", amount_usd=200)],
            estimated_total_usd=200,
        ),
        practical_notes=[],
    )

    def fail_extractor(state, config):
        raise AssertionError("Informational questions must not enter extraction")

    def answer_question(state, config):
        return {
            "response": "Japan uses JPY.",
            "messages": [AIMessage(content="Japan uses JPY.")],
        }

    monkeypatch.setattr(builder, "extractor_node", fail_extractor)
    monkeypatch.setattr(builder, "question_responder_node", answer_question)
    graph = builder._build_graph()

    result = graph.invoke(
        {
            "messages": [HumanMessage(content="What currency is used in Japan?")],
            "itinerary": plan,
        }
    )

    assert result["turn_intent"] == "answer_question"
    assert result["response"] == "Japan uses JPY."
    assert result["itinerary"] == plan


def test_chat_request_rejects_user_supplied_guest_nationality():
    with pytest.raises(ValidationError):
        ChatRequest(
            message="Plan a trip.",
            guest_nationality_country_code="BD",
        )


def test_full_graph_invoke_with_user_id_and_mocked_memory(monkeypatch):
    """A graph turn with user_id runs through memory nodes without Mem0."""

    service = Mock()
    service.recall.return_value = ["Traveler prefers vegetarian meals."]
    monkeypatch.setattr(memory_recall, "get_memory_service", lambda: service)
    monkeypatch.setattr(memory_write, "get_memory_service", lambda: service)
    monkeypatch.setattr(
        builder,
        "extractor_node",
        lambda state, config: {
            "trip": Trip(
                origin="Dhaka",
                destination="Tokyo",
                start_date=date.today() + timedelta(days=7),
                end_date=date.today() + timedelta(days=9),
                duration=3,
                budget=1000,
                currency="USD",
                travelers=1,
            ),
            "missing_fields": [],
            "needs_clarification": False,
        },
    )
    monkeypatch.setattr(
        agent,
        "get_tool_enabled_llm",
        lambda: Mock(invoke=Mock(return_value=AIMessage(content="Final itinerary."))),
    )
    plan = TripPlan(
        title="Tokyo Plan",
        origin="Dhaka",
        destination="Tokyo",
        duration_days=3,
        travelers=1,
        summary=None,
        preferences=[],
        days=[
            ItineraryDay(
                day_number=day_number,
                city="Tokyo",
                activities=[Activity(name=f"Activity {day_number}", category="visit")],
            )
            for day_number in range(1, 4)
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Trip", amount_usd=900)],
            estimated_total_usd=900,
            user_budget_usd=1000,
        ),
        practical_notes=[],
    )

    class StructuredModel:
        def with_structured_output(self, schema, *, method):
            return RunnableLambda(lambda _: plan)

    monkeypatch.setattr(
        itinerary_generator,
        "get_gemini_llm",
        lambda: StructuredModel(),
    )

    async def skip_place_enrichment(state, config):
        return {"itinerary": state.get("itinerary")}

    monkeypatch.setattr(builder, "place_enrichment_node", skip_place_enrichment)

    async def skip_image_enrichment(state, config):
        return {"itinerary": state.get("itinerary")}

    monkeypatch.setattr(builder, "image_enrichment_node", skip_image_enrichment)

    async def skip_weather_enrichment(state, config):
        return {"itinerary": state.get("itinerary")}

    monkeypatch.setattr(builder, "weather_enrichment_node", skip_weather_enrichment)

    async def skip_routing_enrichment(state, config):
        return {"itinerary": state.get("itinerary")}

    monkeypatch.setattr(builder, "routing_enrichment_node", skip_routing_enrichment)

    async def skip_flight_recommendation(state, config):
        return {"itinerary": state.get("itinerary")}

    monkeypatch.setattr(
        builder,
        "flight_recommendation_node",
        skip_flight_recommendation,
    )

    graph = builder._build_graph()
    result = asyncio.run(
        graph.ainvoke(
            {
                "messages": [
                    {"role": "user", "content": "Plan Tokyo for 3 days under $1000."}
                ],
                "user_id": "user-123",
            },
            config={"configurable": {"thread_id": "test-thread-memory"}},
        )
    )

    assert result["user_id"] == "user-123"
    assert result["long_term_memories"] == ["Traveler prefers vegetarian meals."]
    assert result["itinerary"].destination == "Tokyo"
    assert result["response"].startswith("# Tokyo Plan")
