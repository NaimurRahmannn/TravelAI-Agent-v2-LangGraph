from collections.abc import Mapping, Sequence
from time import perf_counter
from typing import Any

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
    stored_response = state.get("response", "")
    if isinstance(final_message, AIMessage):
        message_response = _message_content_to_text(final_message.content)
        # Tool-calling AI messages commonly have empty content. On an approval
        # rejection, the approval node has already written the user-facing
        # explanation to state, so preserve it instead of replacing it with "".
        response = message_response if message_response.strip() else stored_response
    else:
        # No fresh AI message to read from (e.g. edge case) — fall back
        # to whatever was last stored, instead of caching it as truth.
        response = stored_response

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


def _message_content_to_text(content: Any) -> str:
    """Convert plain or block-based LangChain message content into clean text.

    Newer Gemini models can return a list of content blocks such as
    ``[{"type": "text", "text": "...", "extras": {...}}]``. Rendering that
    value with ``str`` leaks the provider's transport structure to the user, so
    only the user-facing text from each block is retained here.
    """

    if isinstance(content, str):
        return content

    if isinstance(content, Mapping):
        text = content.get("text")
        return text if isinstance(text, str) else ""

    if isinstance(content, Sequence) and not isinstance(content, (bytes, bytearray)):
        text_parts = [_message_content_to_text(block) for block in content]
        return "\n".join(part for part in text_parts if part)

    # Unknown provider metadata should never become part of the user response.
    return ""
