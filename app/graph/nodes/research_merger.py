from time import perf_counter

from langchain_core.runnables import RunnableConfig

from app.core.logging import get_logger
from app.graph.subgraphs.research_state import ResearchState

logger = get_logger(__name__)


def research_merger(
    state: ResearchState,
    config: RunnableConfig,
) -> dict[str, dict[str, str]]:
    """Combine parallel research outputs into a unified summary."""

    started_at = perf_counter()
    research_results = state.get("research_results", {})
    result_keys = [
        key
        for key in research_results
        if key != "summary"
    ]
    logger.info(
        "ResearchGraph.Merger entered result_count=%s result_keys=%s",
        len(result_keys),
        result_keys,
    )

    if result_keys:
        summary = "\n".join(
            research_results[key]
            for key in sorted(result_keys)
        )
    else:
        summary = "No additional destination research was available."

    duration = perf_counter() - started_at
    logger.info(
        "ResearchGraph.Merger completed result_count=%s result_keys=%s duration=%.4fs",
        len(result_keys),
        result_keys,
        duration,
    )
    return {
        "research_results": {
            "summary": summary,
        },
    }
