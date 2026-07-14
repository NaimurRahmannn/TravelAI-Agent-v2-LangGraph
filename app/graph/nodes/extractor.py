from langchain_core.messages import HumanMessage, SystemMessage

from app.llm import get_llm
from app.models import Trip
from app.graph.state import TravelState
from app.graph.prompts.extractor import EXTRACT_TRIP_PROMPT


def extractor_node(state: TravelState):

    llm = get_llm()

    structured_llm = llm.with_structured_output(Trip)

    messages = [
        SystemMessage(content=EXTRACT_TRIP_PROMPT),
        *state["messages"],
    ]

    trip = structured_llm.invoke(messages)

    return {
        "trip": trip
    }