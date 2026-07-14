from time import perf_counter

from langchain_core.runnables import RunnableConfig
from langgraph.types import Send

from app.core.logging import get_logger
from app.graph.subgraphs.research_state import ResearchState
from app.models import Trip

logger = get_logger(__name__)


def research_dispatcher_node(
    state: ResearchState,
    config: RunnableConfig,
) -> dict[str, list[str]]:
    """Record the independent research tasks needed for an extracted trip."""

    started_at = perf_counter()
    tasks = _get_research_tasks(state.get("trip"))
    logger.info(
        "ResearchGraph.Dispatcher entered task_count=%s tasks=%s",
        len(tasks),
        tasks,
    )

    duration = perf_counter() - started_at
    logger.info(
        "ResearchGraph.Dispatcher exited task_count=%s tasks=%s duration=%.4fs",
        len(tasks),
        tasks,
        duration,
    )
    return {
        "pending_tasks": tasks,
    }


def research_dispatcher(
    state: ResearchState,
) -> list[Send]:
    """Create parallel Send tasks for independent destination research."""

    started_at = perf_counter()
    trip = state.get("trip")
    tasks = _get_research_tasks(trip)
    logger.info(
        "ResearchGraph.Dispatcher creating parallel tasks task_count=%s tasks=%s",
        len(tasks),
        tasks,
    )

    sends: list[Send] = []
    if "weather" in tasks:
        sends.append(
            Send(
                "weather_worker",
                {
                    "trip": trip,
                },
            )
        )

    if "currency" in tasks:
        sends.append(
            Send(
                "currency_worker",
                {
                    "trip": trip,
                },
            )
        )

    if "visa" in tasks:
        sends.append(
            Send(
                "visa_worker",
                {
                    "trip": trip,
                },
            )
        )

    duration = perf_counter() - started_at
    logger.info(
        "ResearchGraph.Dispatcher created parallel tasks send_count=%s tasks=%s duration=%.4fs",
        len(sends),
        tasks,
        duration,
    )
    return sends


def _get_research_tasks(trip: Trip | None) -> list[str]:
    """Return research task names that can run for the extracted trip."""

    if trip is None or not trip.destination:
        return []

    tasks = [
        "weather",
        "currency",
    ]

    if trip.origin:
        tasks.append("visa")

    return tasks
