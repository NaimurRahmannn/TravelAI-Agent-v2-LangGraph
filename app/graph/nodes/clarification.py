from langchain_core.runnables import RunnableConfig

from app.core.logging import get_logger
from app.graph.prompts.clarification import clarification_prompt
from app.graph.state import TravelState
from app.llm import get_llm

logger = get_logger(__name__)


def clarification_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, str]:
    """Generate a friendly clarification question for missing trip fields."""

    logger.info("clarification_node started")
    llm = get_llm()

    chain = clarification_prompt | llm

    response = chain.invoke(
        {
            "missing_fields": state["missing_fields"],
        }
    )

    result = {
        "response": response.content,
    }
    logger.info("clarification_node finished")
    return result
