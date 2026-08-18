from unittest.mock import Mock

from langchain_core.messages import AIMessage
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

    graph = builder._build_graph()
    result = graph.invoke(
        {
            "messages": [
                {"role": "user", "content": "Plan Tokyo for 3 days under $1000."}
            ],
            "user_id": "user-123",
        },
        config={"configurable": {"thread_id": "test-thread-memory"}},
    )

    assert result["user_id"] == "user-123"
    assert result["long_term_memories"] == ["Traveler prefers vegetarian meals."]
    assert result["itinerary"].destination == "Tokyo"
    assert result["response"].startswith("# Tokyo Plan")
