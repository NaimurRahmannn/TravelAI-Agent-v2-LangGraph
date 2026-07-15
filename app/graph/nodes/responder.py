from time import perf_counter

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig

from app.core.logging import get_logger

from app.graph.state import TravelState

logger = get_logger(__name__)


def responder_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, str]:
    """Convert the final AI message into the graph response."""

    started_at = perf_counter()
    messages: list[BaseMessage] = state["messages"]
    tool_names = _get_latest_tool_names(messages)
    logger.info(
        "responder_node entered tool_count=%s tool_names=%s",
        len(tool_names),
        tool_names,
    )

    final_message = messages[-1] if messages else None
    if isinstance(final_message, AIMessage):
        response = _message_content_to_text(final_message.content)
    else:
        # No fresh AI message to read from (e.g. edge case) — fall back
        # to whatever was last stored, instead of caching it as truth.
        response = state.get("response", "")

    result = {
        "response": response,
    }
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


def _message_content_to_text(content: str | list[dict[str, object]] | object) -> str:
    """Convert LangChain message content into response text."""

    if isinstance(content, str):
        return content

    return str(content)
