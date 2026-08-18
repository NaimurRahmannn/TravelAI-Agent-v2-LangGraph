from time import perf_counter

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig

from app.core.logging import get_logger
from app.graph.state import TravelState
from app.models import TripPlan
from app.services.itinerary_renderer import render_itinerary
from app.services.message_content import message_content_to_text

logger = get_logger(__name__)


def responder_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, str | TripPlan]:
    """Convert the final AI message into the graph response."""

    started_at = perf_counter()
    messages: list[BaseMessage] = state["messages"]
    tool_names = _get_latest_tool_names(messages)
    logger.info(
        "responder_node entered tool_count=%s tool_names=%s",
        len(tool_names),
        tool_names,
    )

    itinerary = state.get("itinerary")
    if itinerary is not None and not isinstance(itinerary, TripPlan):
        try:
            itinerary = TripPlan.model_validate(itinerary)
        except Exception:
            logger.warning(
                "invalid checkpointed itinerary ignored; using text fallback",
                exc_info=True,
            )
            itinerary = None

    final_message = messages[-1] if messages else None
    stored_response = state.get("response", "")
    if itinerary is not None:
        response = render_itinerary(itinerary)
    elif isinstance(final_message, AIMessage):
        message_response = message_content_to_text(final_message.content)
        # Tool-calling AI messages commonly have empty content. On an approval
        # rejection, the approval node has already written the user-facing
        # explanation to state, so preserve it instead of replacing it with "".
        response = message_response if message_response.strip() else stored_response
    else:
        # No fresh AI message to read from (e.g. edge case) — fall back
        # to whatever was last stored, instead of caching it as truth.
        response = stored_response

    result: dict[str, str | TripPlan] = {"response": response}
    if itinerary is not None:
        result["itinerary"] = itinerary
    duration = perf_counter() - started_at
    logger.info(
        "responder_node exited tool_count=%s tool_names=%s duration=%.4fs",
        len(tool_names),
        tool_names,
        duration,
    )
    return result


def _get_latest_tool_names(messages: list[BaseMessage]) -> list[str]:
    """Return tool names requested by the latest AI message."""

    if not messages:
        return []

    last_message = messages[-1]
    if not isinstance(last_message, AIMessage):
        return []

    return [
        tool_call["name"]
        for tool_call in last_message.tool_calls
    ]
