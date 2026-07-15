from time import perf_counter

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig

from app.core.logging import get_logger
from app.llm import get_llm
from app.models import Trip
from app.models.itinerary import Itinerary, ItineraryDay

from app.graph.prompts.itinerary import itinerary_prompt
from app.graph.state import TravelState

logger = get_logger(__name__)


def itinerary_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, list[AIMessage]]:
    """Convert the agent's draft answer into a deterministic, structured itinerary."""

    started_at = perf_counter()
    logger.info("itinerary_node entered")

    trip = state.get("trip")
    duration_days = trip.duration if trip and trip.duration else 1
    draft_answer = _get_latest_ai_text(state["messages"])
    research_notes = state.get("research_results", {}).get("summary") or "None"

    llm = get_llm()
    chain = itinerary_prompt | llm.with_structured_output(Itinerary)

    itinerary = chain.invoke(
        {
            "trip_details": trip.model_dump_json() if trip else "None",
            "research_notes": research_notes,
            "draft_answer": draft_answer or "None",
        },
        config=config,
    )

    itinerary = _normalize_day_count(itinerary, duration_days)
    rendered = _render_markdown(itinerary, trip)

    duration = perf_counter() - started_at
    logger.info("itinerary_node exited duration=%.4fs", duration)

    return {
        "messages": [AIMessage(content=rendered)],
    }


def _get_latest_ai_text(messages: list[BaseMessage]) -> str:
    """Return the most recent non-empty AI message content, if any."""

    for message in reversed(messages):
        if isinstance(message, AIMessage) and message.content:
            return str(message.content)

    return ""


def _normalize_day_count(itinerary: Itinerary, duration_days: int) -> Itinerary:
    """Force the itinerary to have exactly `duration_days` days."""

    days = list(itinerary.days)

    if len(days) > duration_days:
        days = days[:duration_days]
    elif len(days) < duration_days:
        for day_number in range(len(days) + 1, duration_days + 1):
            days.append(
                ItineraryDay(
                    day_number=day_number,
                    title="Flexible day",
                    activities=[
                        "Free time to explore based on your interests, or "
                        "rest before the next leg of the trip.",
                    ],
                )
            )

    for index, day in enumerate(days, start=1):
        day.day_number = index

    itinerary.days = days
    itinerary.duration_days = duration_days
    return itinerary


def _render_markdown(itinerary: Itinerary, trip: Trip | None) -> str:
    """Deterministically render the structured itinerary as markdown."""

    lines: list[str] = []

    for day in itinerary.days:
        activities = (
            "; ".join(day.activities) if day.activities else "Flexible / free time."
        )
        lines.append(f"**Day {day.day_number}: {day.title}** - {activities}")

    breakdown = itinerary.budget_breakdown
    breakdown_parts = [
        ("Flights", breakdown.flights),
        ("Accommodation", breakdown.accommodation),
        ("Transport", breakdown.transport),
        ("Food & activities", breakdown.food_and_activities),
    ]
    known_parts = [
        (label, value) for label, value in breakdown_parts if value is not None
    ]
    computed_total = sum(value for _, value in known_parts) if known_parts else None

    lines.append("")
    lines.append("**Budget breakdown:**")
    for label, value in known_parts:
        lines.append(f"- {label}: ${value:,.0f}")

    if computed_total is not None:
        lines.append(f"- **Total (estimated): ${computed_total:,.0f}**")
        if trip and trip.budget is not None and computed_total > trip.budget:
            lines.append(
                f"- Note: this estimate is above your stated budget of "
                f"${trip.budget:,.0f}; consider adjusting accommodation or "
                "activities."
            )

    notes = [
        note
        for note in (
            itinerary.currency_note,
            itinerary.weather_note,
            itinerary.visa_note,
        )
        if note
    ]
    if notes:
        lines.append("")
        lines.append("**Practical notes:**")
        for note in notes:
            lines.append(f"- {note}")

    return "\n".join(lines)