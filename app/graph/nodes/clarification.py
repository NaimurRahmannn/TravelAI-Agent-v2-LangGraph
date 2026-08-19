from time import perf_counter

from langchain_core.runnables import RunnableConfig

from app.core.logging import get_logger
from app.graph.prompts.clarification import clarification_prompt
from app.graph.state import TravelState
from app.llm import get_groq_llm

logger = get_logger(__name__)

DATE_SELECTION_RESPONSE = (
    "When are you traveling? Select your exact travel dates below."
)


def clarification_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, str | list[str]]:
    """Generate a friendly clarification question for missing trip fields."""

    started_at = perf_counter()
    logger.info(
        "clarification_node entered tool_count=%s tool_names=%s",
        0,
        [],
    )
    missing_fields = state["missing_fields"]
    if "dates" in missing_fields:
        result = {
            "response": DATE_SELECTION_RESPONSE,
            "missing_fields": missing_fields,
        }
        duration = perf_counter() - started_at
        logger.info(
            "clarification_node exited date_selection=true duration=%.4fs",
            duration,
        )
        return result

    llm = get_groq_llm()

    chain = clarification_prompt | llm

    response = chain.invoke(
        {
            "missing_fields": missing_fields,
        }
    )

    result = {
        "response": response.content,
        "missing_fields": missing_fields,
    }
    duration = perf_counter() - started_at
    logger.info(
        "clarification_node exited tool_count=%s tool_names=%s duration=%.4fs",
        0,
        [],
        duration,
    )
    return result
