from time import perf_counter

from langchain_core.runnables import RunnableConfig

from app.core.logging import get_logger
from app.graph.state import TravelState

logger = get_logger(__name__)


def planner_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, dict[str, str]]:
    """Plan the next graph action for the travel request."""

    started_at = perf_counter()
    logger.info(
        "planner_node entered tool_count=%s tool_names=%s",
        0,
        [],
    )
    result = {
        "planner": {
            "current_step": "Planning",
            "next_action": "finish",
        }
    }
    duration = perf_counter() - started_at
    logger.info(
        "planner_node exited tool_count=%s tool_names=%s duration=%.4fs",
        0,
        [],
        duration,
    )
    return result
