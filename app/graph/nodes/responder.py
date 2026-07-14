from langchain_core.runnables import RunnableConfig

from app.llm import get_llm

from app.graph.prompts.responder import responder_prompt
from app.graph.state import TravelState


def responder_node(
    state: TravelState,
    config: RunnableConfig,
):
    llm = get_llm()

    chain = responder_prompt | llm

    response = chain.invoke(
        {
            "trip": state["trip"],
        }
    )

    return {
        "response": response.content,
    }