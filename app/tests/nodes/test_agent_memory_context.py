from datetime import date

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.graph.nodes.agent import _build_agent_messages
from app.models import Trip


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
    assert "complete final itinerary directly" in str(messages[0].content)


def test_agent_uses_date_derived_scope_and_drops_superseded_duration_history():
    messages = _build_agent_messages(
        {
            "trip": Trip(
                origin="Bangladesh",
                destination="Japan",
                start_date=date(2026, 8, 29),
                end_date=date(2026, 9, 1),
                duration=4,
                budget=2000,
                currency="USD",
                travelers=2,
            ),
            "messages": [
                HumanMessage(content="Plan a 7-day Japan trip."),
                AIMessage(content="Select exact dates."),
                HumanMessage(content="Travel dates: 2026-08-29 to 2026-09-01"),
            ],
        }
    )

    context = str(messages[0].content)
    human_messages = [
        str(message.content)
        for message in messages
        if isinstance(message, HumanMessage)
    ]

    assert "Authoritative trip length: exactly 4 days" in context
    assert "Output exactly 4 numbered day sections" in context
    assert "Never include airfare, flights, hotels, accommodation" in context
    assert human_messages == ["Travel dates: 2026-08-29 to 2026-09-01"]
