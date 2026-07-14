from langchain_core.runnables import RunnableConfig

from app.core.logging import get_logger
from app.llm import get_llm

from app.graph.prompts.responder import responder_prompt
from app.graph.state import TravelState

logger = get_logger(__name__)


def responder_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, str]:
    """Generate a natural-language response for the extracted trip."""

    logger.info("responder_node started")
    llm = get_llm()

    chain = responder_prompt | llm

    response = chain.invoke(
        {
            "trip": state["trip"],
        }
    )

    result = {
        "response": response.content,
    }
    logger.info("responder_node finished")
    return result
