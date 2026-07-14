from langchain_core.runnables import RunnableConfig

from app.llm import get_llm
from app.models import Trip

from app.graph.prompts.extractor import extractor_prompt
from app.graph.state import TravelState


def extractor_node(
    state: TravelState,
    config: RunnableConfig,
):
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

    return {
        "trip": trip,
    }