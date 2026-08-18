from langchain_core.messages import AIMessage, HumanMessage

from app.graph.nodes.responder import responder_node
from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    ItineraryDay,
    TripPlan,
)


def test_responder_preserves_rejection_when_tool_message_content_is_empty():
    """An empty tool-call message must not erase the approval rejection text."""

    rejection = (
        "Approval rejected for hotel_booking. "
        "I did not execute the requested action."
    )
    result = responder_node(
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "book_hotel",
                            "args": {},
                            "id": "call-1",
                            "type": "tool_call",
                        }
                    ],
                )
            ],
            "response": rejection,
        },
        config={},
    )

    assert result == {"response": rejection}


def test_responder_prefers_non_empty_latest_ai_message():
    """A fresh final AI response takes precedence over an older state value."""

    result = responder_node(
        {
            "messages": [AIMessage(content="Your final itinerary is ready.")],
            "response": "Older response",
        },
        config={},
    )

    assert result == {"response": "Your final itinerary is ready."}


def test_responder_extracts_text_from_gemini_content_blocks():
    """Gemini block metadata must not leak into the user-facing response."""

    result = responder_node(
        {
            "messages": [
                AIMessage(
                    content=[
                        {
                            "type": "text",
                            "text": "### 5-Day Thailand Itinerary",
                            "extras": {"signature": "provider-internal-value"},
                        }
                    ]
                )
            ],
            "response": "",
        },
        config={},
    )

    assert result == {"response": "### 5-Day Thailand Itinerary"}


def test_responder_joins_multiple_text_blocks_and_ignores_metadata():
    """Multiple content blocks render as text without reasoning metadata."""

    result = responder_node(
        {
            "messages": [
                AIMessage(
                    content=[
                        {"type": "text", "text": "First section."},
                        {"type": "thinking", "thinking": "Internal reasoning"},
                        {"type": "text", "text": "Second section."},
                    ]
                )
            ],
            "response": "",
        },
        config={},
    )

    assert result == {"response": "First section.\nSecond section."}


def test_responder_uses_stored_response_without_final_ai_message():
    """The existing fallback remains valid when the last message is not from AI."""

    result = responder_node(
        {
            "messages": [HumanMessage(content="Cancel that action.")],
            "response": "The action was cancelled.",
        },
        config={},
    )

    assert result == {"response": "The action was cancelled."}


def test_responder_renders_structured_itinerary_as_source_of_truth():
    plan = TripPlan(
        title="Thailand Plan",
        origin="Dhaka",
        destination="Thailand",
        duration_days=1,
        travelers=2,
        summary=None,
        preferences=[],
        days=[
            ItineraryDay(
                day_number=1,
                city="Bangkok",
                activities=[Activity(name="Wat Arun", category="culture")],
            )
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Activities", amount_usd=50)],
            estimated_total_usd=50,
            user_budget_usd=100,
        ),
        practical_notes=[],
    )

    result = responder_node(
        {
            "messages": [AIMessage(content="This text is no longer authoritative.")],
            "response": "Older response",
            "itinerary": plan,
        },
        config={},
    )

    assert result["itinerary"] == plan
    assert result["response"].startswith("# Thailand Plan")
    assert "Wat Arun" in result["response"]
    assert "no longer authoritative" not in result["response"]


def test_responder_ignores_invalid_checkpointed_itinerary():
    """Invalid structured state must preserve the usable agent text fallback."""

    result = responder_node(
        {
            "messages": [AIMessage(content="Usable agent response.")],
            "response": "Older response",
            "itinerary": {"title": "Incomplete stale plan"},
        },
        config={},
    )

    assert result == {"response": "Usable agent response."}
