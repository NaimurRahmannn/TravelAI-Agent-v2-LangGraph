from langchain_core.messages import HumanMessage, SystemMessage

from app.graph.nodes.agent import _build_agent_messages


def test_agent_messages_include_long_term_memories_separately():
    """Agent prompt includes recalled memories as a separate system message."""

    messages = _build_agent_messages(
        {
            "messages": [HumanMessage(content="Plan dinner in Tokyo.")],
            "long_term_memories": ["Traveler is vegetarian."],
        }
    )

    memory_messages = [
        message
        for message in messages
        if isinstance(message, SystemMessage)
        and "Known facts about this traveler" in str(message.content)
    ]

    assert len(memory_messages) == 1
    assert "Traveler is vegetarian." in str(memory_messages[0].content)
