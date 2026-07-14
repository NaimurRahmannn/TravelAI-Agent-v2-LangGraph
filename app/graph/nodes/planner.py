from langchain_core.runnables import RunnableConfig

from app.core.logging import get_logger
from app.graph.state import TravelState

logger = get_logger(__name__)


def planner_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, dict[str, str]]:
    """Plan the next graph action for the travel request."""

    logger.info("planner_node started")
    result = {
        "planner": {
            "current_step": "Planning",
            "next_action": "finish",
        }
    }
    logger.info("planner_node finished")
    return result
