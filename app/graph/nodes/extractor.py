from time import perf_counter

from langchain_core.runnables import RunnableConfig

from app.core.logging import get_logger
from app.llm import get_llm
from app.models import Trip

from app.graph.prompts.extractor import extractor_prompt
from app.graph.state import TravelState

logger = get_logger(__name__)


def extractor_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, Trip | list[str] | bool]:
    """Extract structured trip details from the conversation state."""

    started_at = perf_counter()
    logger.info(
        "extractor_node entered tool_count=%s tool_names=%s",
        0,
        [],
    )
    llm = get_llm()

    chain = (
        extractor_prompt
        | llm.with_structured_output(Trip)
    )

    trip = chain.invoke(
        {
            "messages": state["messages"],
        }
    )

    missing_fields = _get_missing_required_fields(trip)
    result = {
        "trip": trip,
        "missing_fields": missing_fields,
        "needs_clarification": len(missing_fields) > 0,
    }
    duration = perf_counter() - started_at
    logger.info(
        "extractor_node exited tool_count=%s tool_names=%s duration=%.4fs",
        0,
        [],
        duration,
    )
    return result


def _get_missing_required_fields(trip: Trip) -> list[str]:
    """Return required trip fields that were not extracted."""

    missing_fields: list[str] = []

    if not trip.destination:
        missing_fields.append("destination")

    if trip.budget is None:
        missing_fields.append("budget")

    if trip.duration is None:
        missing_fields.append("duration")

    return missing_fields
