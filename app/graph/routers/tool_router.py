from time import perf_counter
from typing import Literal

from langchain_core.messages import AIMessage, BaseMessage

from app.core.logging import get_logger
from app.graph.state import TravelState

logger = get_logger(__name__)


def tool_router(
    state: TravelState,
) -> Literal["approval_gate", "responder"]:
    """Route tool-call requests toward approval or finish with responder."""

    started_at = perf_counter()
    messages: list[BaseMessage] = state["messages"]
    tool_names = _get_latest_tool_names(messages)
    logger.info(
        "tool_router entered tool_count=%s tool_names=%s",
        len(tool_names),
        tool_names,
    )

    if not messages:
        _log_exit("responder", tool_names, started_at)
        return "responder"

    last_message = messages[-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        _log_exit("approval_gate", tool_names, started_at)
        return "approval_gate"

    _log_exit("responder", tool_names, started_at)
    return "responder"


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


def _log_exit(
    route: Literal["approval_gate", "responder"],
    tool_names: list[str],
    started_at: float,
) -> None:
    """Log the selected tool route and execution duration."""

    duration = perf_counter() - started_at
    logger.info(
        "tool_router exited route=%s tool_count=%s tool_names=%s duration=%.4fs",
        route,
        len(tool_names),
        tool_names,
        duration,
    )
