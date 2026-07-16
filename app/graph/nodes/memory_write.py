from time import perf_counter
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from app.core.logging import get_logger
from app.graph.state import TravelState
from app.services.memory_service import get_memory_service

logger = get_logger(__name__)


def memory_write_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, Any]:
    """Persist durable traveler facts extracted from this turn into Mem0."""

    started_at = perf_counter()
    user_id = state.get("user_id")
    latest_user_message = _latest_user_message(state)
    response = state.get("response", "")

    if user_id and latest_user_message and response:
        get_memory_service().remember(
            messages=[
                {"role": "user", "content": latest_user_message},
                {"role": "assistant", "content": response},
            ],
            user_id=user_id,
        )

    duration = perf_counter() - started_at
    logger.info(
        "memory_write_node exited user_id=%s duration=%.4fs",
        user_id,
        duration,
    )
    return {}


def _latest_user_message(state: TravelState) -> str:
    """Return the latest human message content, or an empty string."""

    for message in reversed(state.get("messages", [])):
        if isinstance(message, HumanMessage):
            return str(message.content)

    return ""