from unittest.mock import Mock

from langchain_core.messages import AIMessage, HumanMessage

from app.graph.nodes import memory_recall


def test_memory_recall_calls_service_with_latest_human_message(monkeypatch):
    """Recall uses the latest human message and user_id."""

    service = Mock()
    service.recall.return_value = ["Traveler prefers vegetarian meals."]
    monkeypatch.setattr(memory_recall, "get_memory_service", lambda: service)

    result = memory_recall.memory_recall_node(
        {
            "user_id": "user-123",
            "messages": [
                HumanMessage(content="I am vegetarian."),
                AIMessage(content="Noted."),
                HumanMessage(content="Plan dinner in Tokyo."),
            ],
        },
        config={},
    )

    service.recall.assert_called_once_with(
        "Plan dinner in Tokyo.",
        user_id="user-123",
    )
    assert result == {"long_term_memories": ["Traveler prefers vegetarian meals."]}


def test_memory_recall_noops_without_user_id(monkeypatch):
    """Recall skips anonymous callers and returns an empty memory list."""

    service = Mock()
    monkeypatch.setattr(memory_recall, "get_memory_service", lambda: service)

    result = memory_recall.memory_recall_node(
        {"messages": [HumanMessage(content="Plan a trip.")]},
        config={},
    )

    service.recall.assert_not_called()
    assert result == {"long_term_memories": []}


def test_memory_recall_noops_without_human_message(monkeypatch):
    """Recall skips turns that have no human message to search with."""

    service = Mock()
    monkeypatch.setattr(memory_recall, "get_memory_service", lambda: service)

    result = memory_recall.memory_recall_node(
        {"user_id": "user-123", "messages": [AIMessage(content="Hello.")]},
        config={},
    )

    service.recall.assert_not_called()
    assert result == {"long_term_memories": []}
