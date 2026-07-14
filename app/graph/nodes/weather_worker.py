from time import perf_counter

from langchain_core.runnables import RunnableConfig

from app.core.logging import get_logger
from app.graph.subgraphs.research_state import ResearchState

logger = get_logger(__name__)


def weather_worker(
    state: ResearchState,
    config: RunnableConfig,
) -> dict[str, dict[str, str]]:
    """Research likely weather for the extracted destination."""

    started_at = perf_counter()
    trip = state["trip"]
    destination = trip.destination if trip and trip.destination else "the destination"
    logger.info("ResearchGraph.Worker.weather entered destination=%s", destination)

    result = (
        f"Weather in {destination}: expect mild to warm conditions around "
        "18-27C depending on season, with a practical chance of rain. Pack "
        "layers and a compact umbrella."
    )

    duration = perf_counter() - started_at
    logger.info(
        "ResearchGraph.Worker.weather exited destination=%s duration=%.4fs",
        destination,
        duration,
    )
    return {
        "research_results": {
            "weather": result,
        },
    }
