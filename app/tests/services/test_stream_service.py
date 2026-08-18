from app.services.stream_service import StreamService
from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    ItineraryDay,
    TripPlan,
)


def test_responder_end_is_normalized_as_final_response():
    """The rendered graph response replaces intermediate model token streams."""

    event = {
        "event": "on_chain_end",
        "metadata": {"langgraph_node": "responder"},
        "data": {"output": {"response": "Final rendered itinerary."}},
    }

    result = StreamService()._normalize_event(event, "thread-123")

    assert result is not None
    assert result["event_type"] == "final_response"
    assert result["node"] == "responder"
    assert result["content"] == "Final rendered itinerary."
    assert result["thread_id"] == "thread-123"
    assert result["itinerary"] is None


def test_clarification_end_is_normalized_as_final_response():
    """Clarification-only graph turns also produce an authoritative response."""

    event = {
        "event": "on_chain_end",
        "metadata": {"langgraph_node": "clarification"},
        "data": {"output": {"response": "What is your budget?"}},
    }

    result = StreamService()._normalize_event(event, "thread-123")

    assert result is not None
    assert result["event_type"] == "final_response"
    assert result["content"] == "What is your budget?"
    assert result["itinerary"] is None


def test_internal_node_end_remains_a_diagnostic_event():
    """Internal structured outputs must not be presented as the final answer."""

    event = {
        "event": "on_chain_end",
        "metadata": {"langgraph_node": "extractor"},
        "data": {"output": {"response": "Internal extractor output"}},
    }

    result = StreamService()._normalize_event(event, "thread-123")

    assert result is not None
    assert result["event_type"] == "on_chain_end"


def test_responder_final_event_serializes_structured_itinerary():
    plan = TripPlan(
        title="Thailand Plan",
        origin="Dhaka",
        destination="Thailand",
        duration_days=1,
        travelers=1,
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
    event = {
        "event": "on_chain_end",
        "metadata": {"langgraph_node": "responder"},
        "data": {"output": {"response": "# Thailand Plan", "itinerary": plan}},
    }

    result = StreamService()._normalize_event(event, "thread-123")

    assert result is not None
    assert result["event_type"] == "final_response"
    assert result["itinerary"]["destination"] == "Thailand"
    formatted = StreamService()._format_sse(result)
    assert '"itinerary": {' in formatted
    assert '"destination": "Thailand"' in formatted
