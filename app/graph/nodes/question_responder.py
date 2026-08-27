from time import perf_counter

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from app.core.logging import get_logger
from app.graph.state import TravelState
from app.llm import get_gemini_llm
from app.models import Trip, TripPlan
from app.services.message_content import message_content_to_text

logger = get_logger(__name__)


def question_responder_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, object]:
    """Answer one focused question without modifying checkpointed trip state."""

    started_at = perf_counter()
    question = _latest_user_message(state)
    context = _traveler_context(state)
    try:
        response = get_gemini_llm().invoke(
            [
                SystemMessage(
                    content=(
                        "Answer the traveler's latest question directly and concisely. "
                        "Use the saved trip context when relevant. Do not create, "
                        "rewrite, extend, or render an itinerary. Do not claim live "
                        "prices, availability, safety conditions, entry rules, or "
                        "weather unless trusted context explicitly supplies them. If "
                        "current information is required but unavailable, explain what "
                        "the traveler should verify."
                    )
                ),
                SystemMessage(content=f"Saved travel context:\n{context}"),
                HumanMessage(content=question),
            ],
            config=config,
        )
        text = message_content_to_text(response.content).strip()
        if not text:
            raise ValueError("Question responder returned empty content")
    except Exception as exc:
        logger.warning(
            "question_response_unavailable error_type=%s",
            type(exc).__name__,
        )
        text = (
            "I couldn't answer that question right now. Your existing trip plan "
            "has been kept unchanged—please try asking again."
        )

    logger.info(
        "question_responder_node exited duration=%.4fs",
        perf_counter() - started_at,
    )
    return {"response": text, "messages": [AIMessage(content=text)]}


def _latest_user_message(state: TravelState) -> str:
    for message in reversed(state.get("messages", [])):
        if isinstance(message, HumanMessage):
            return message_content_to_text(message.content)
    return ""


def _traveler_context(state: TravelState) -> str:
    try:
        trip = Trip.model_validate(state.get("trip"))
    except ValueError:
        trip = None
    try:
        itinerary = TripPlan.model_validate(state.get("itinerary"))
    except ValueError:
        itinerary = None
    parts: list[str] = []
    if trip is not None:
        parts.append(f"Trip facts: {trip.model_dump_json()}")
    if itinerary is not None:
        parts.append(
            "Saved itinerary summary: "
            f"title={itinerary.title!r}, destination={itinerary.destination!r}, "
            f"dates={itinerary.start_date} through {itinerary.end_date}, "
            f"days={itinerary.duration_days}, travelers={itinerary.travelers}, "
            f"preferences={itinerary.preferences!r}"
        )
    memories = state.get("long_term_memories", [])
    if memories:
        parts.append("Relevant traveler memories: " + "; ".join(memories))
    return "\n".join(parts) or "No saved trip context."
