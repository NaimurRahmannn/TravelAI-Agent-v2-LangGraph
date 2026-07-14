from time import perf_counter

from langchain_core.runnables import RunnableConfig

from app.core.logging import get_logger
from app.graph.subgraphs.research_state import ResearchState

logger = get_logger(__name__)


def visa_worker(
    state: ResearchState,
    config: RunnableConfig,
) -> dict[str, dict[str, str]]:
    """Research simple visa guidance for the extracted destination."""

    started_at = perf_counter()
    trip = state["trip"]
    destination = trip.destination if trip and trip.destination else "the destination"
    nationality = trip.origin if trip and trip.origin else "the traveler's nationality"
    logger.info(
        "ResearchGraph.Worker.visa entered destination=%s nationality=%s",
        destination,
        nationality,
    )

    result = (
        f"Visa guidance for {nationality} travelers visiting {destination}: "
        "confirm current entry rules with the official embassy or immigration "
        "website before booking. Requirements may vary by passport, stay "
        "duration, and travel purpose."
    )

    duration = perf_counter() - started_at
    logger.info(
        "ResearchGraph.Worker.visa exited destination=%s nationality=%s duration=%.4fs",
        destination,
        nationality,
        duration,
    )
    return {
        "research_results": {
            "visa": result,
        },
    }
