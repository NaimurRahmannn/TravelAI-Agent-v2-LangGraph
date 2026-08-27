from datetime import date

from langchain_core.messages import AIMessage, HumanMessage

from app.graph.nodes import question_responder
from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    ItineraryDay,
    Trip,
    TripPlan,
)


class _AnswerModel:
    def invoke(self, messages, *, config):
        return AIMessage(content="Japan uses the Japanese yen (JPY).")


def _plan() -> TripPlan:
    return TripPlan(
        title="Japan plan",
        origin="Dhaka",
        destination="Japan",
        start_date=date(2026, 9, 10),
        end_date=date(2026, 9, 12),
        duration_days=3,
        travelers=2,
        preferences=[],
        days=[
            ItineraryDay(
                day_number=number,
                date=date(2026, 9, 9 + number),
                city="Tokyo",
                activities=[Activity(name="Explore Tokyo", category="visit")],
            )
            for number in range(1, 4)
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Local costs", amount_usd=300)],
            estimated_total_usd=300,
        ),
        practical_notes=[],
    )


def test_question_response_does_not_emit_any_trip_state_mutation(monkeypatch):
    plan = _plan()
    trip = Trip(
        origin="Dhaka",
        destination="Japan",
        start_date=plan.start_date,
        end_date=plan.end_date,
        duration=plan.duration_days,
        travelers=plan.travelers,
    )
    monkeypatch.setattr(question_responder, "get_gemini_llm", lambda: _AnswerModel())

    result = question_responder.question_responder_node(
        {
            "messages": [HumanMessage(content="What currency is used in Japan?")],
            "trip": trip,
            "itinerary": plan,
            "travel_selections": {"selected_flight_id": "flight-1"},
        },
        config={},
    )

    assert result["response"] == "Japan uses the Japanese yen (JPY)."
    assert set(result) == {"response", "messages"}
    assert plan.days[0].activities[0].name == "Explore Tokyo"
