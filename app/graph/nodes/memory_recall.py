from time import perf_counter

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from app.core.logging import get_logger
from app.graph.state import TravelState
from app.services.memory_service import get_memory_service

logger = get_logger(__name__)


def memory_recall_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, list[str]]:
    """Recall durable traveler facts from Mem0 for the current user_id."""

    started_at = perf_counter()
    user_id = state.get("user_id")
    query = _latest_user_message(state)

    memories: list[str] = []
    if user_id and query:
        memories = get_memory_service().recall(query, user_id=user_id)

    duration = perf_counter() - started_at
    logger.info(
        "memory_recall_node exited user_id=%s memory_count=%s duration=%.4fs",
        user_id,
        len(memories),
        duration,
    )
    return {"long_term_memories": memories}


def _latest_user_message(state: TravelState) -> str:
    """Return the latest human message content, or an empty string."""

    for message in reversed(state.get("messages", [])):
        if isinstance(message, HumanMessage):
            return str(message.content)

    return ""