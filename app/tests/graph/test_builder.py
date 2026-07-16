from unittest.mock import Mock

from langchain_core.messages import AIMessage

from app.graph import builder
from app.graph.nodes import agent, memory_recall, memory_write
from app.models import Trip
from app.schemas.api import ChatRequest
from app.services.graph_services import GraphService


def test_graph_contains_memory_nodes():
    """Compiled graph exposes the long-term memory nodes."""

    graph = builder._build_graph()

    assert "memory_recall" in graph.nodes
    assert "memory_write" in graph.nodes


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
            "trip": Trip(destination="Tokyo", duration=3, budget=1000, currency="USD"),
            "missing_fields": [],
            "needs_clarification": False,
        },
    )
    monkeypatch.setattr(
        builder,
        "itinerary_node",
        lambda state, config: {
            "messages": [AIMessage(content="Final itinerary.")],
        },
    )
    monkeypatch.setattr(
        agent,
        "get_tool_enabled_llm",
        lambda: Mock(invoke=Mock(return_value=AIMessage(content="Draft itinerary."))),
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
    assert result["response"]
