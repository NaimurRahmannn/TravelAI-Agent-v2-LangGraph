from unittest.mock import Mock

from langchain_core.messages import AIMessage, HumanMessage

from app.graph.nodes import memory_write


def test_memory_write_calls_service_with_turn_messages(monkeypatch):
    """Write persists the latest user message and final response for a user."""

    service = Mock()
    monkeypatch.setattr(memory_write, "get_memory_service", lambda: service)

    result = memory_write.memory_write_node(
        {
            "user_id": "user-123",
            "messages": [
                HumanMessage(content="I prefer slow travel."),
                AIMessage(content="Great."),
                HumanMessage(content="Plan Kyoto."),
            ],
            "response": "A slower Kyoto itinerary would work well.",
        },
        config={},
    )

    service.remember.assert_called_once_with(
        messages=[
            {"role": "user", "content": "Plan Kyoto."},
            {
                "role": "assistant",
                "content": "A slower Kyoto itinerary would work well.",
            },
        ],
        user_id="user-123",
    )
    assert result == {}


def test_memory_write_noops_without_user_id(monkeypatch):
    """Write skips anonymous callers."""

    service = Mock()
    monkeypatch.setattr(memory_write, "get_memory_service", lambda: service)

    result = memory_write.memory_write_node(
        {
            "messages": [HumanMessage(content="I am vegan.")],
            "response": "I will keep that in mind.",
        },
        config={},
    )

    service.remember.assert_not_called()
    assert result == {}


def test_memory_write_noops_without_response(monkeypatch):
    """Write skips incomplete turns without a final response."""

    service = Mock()
    monkeypatch.setattr(memory_write, "get_memory_service", lambda: service)

    result = memory_write.memory_write_node(
        {
            "user_id": "user-123",
            "messages": [HumanMessage(content="I am vegan.")],
        },
        config={},
    )

    service.remember.assert_not_called()
    assert result == {}
