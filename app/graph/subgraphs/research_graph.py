from typing import Any

from langgraph.graph import END, START, StateGraph

from app.graph.nodes.currency_worker import currency_worker
from app.graph.nodes.research_dispatcher import (
    research_dispatcher,
    research_dispatcher_node,
)
from app.graph.nodes.research_merger import research_merger
from app.graph.nodes.visa_worker import visa_worker
from app.graph.nodes.weather_worker import weather_worker
from app.graph.state import TravelState


def build_research_graph() -> Any:
    """Build the parallel research subgraph using LangGraph Send."""

    builder = StateGraph(TravelState)

    builder.add_node("research_dispatcher", research_dispatcher_node)
    builder.add_node("weather_worker", weather_worker)
    builder.add_node("currency_worker", currency_worker)
    builder.add_node("visa_worker", visa_worker)
    builder.add_node("research_merger", research_merger)

    builder.add_edge(START, "research_dispatcher")
    builder.add_conditional_edges(
        "research_dispatcher",
        research_dispatcher,
        [
            "weather_worker",
            "currency_worker",
            "visa_worker",
        ],
    )
    builder.add_edge("weather_worker", "research_merger")
    builder.add_edge("currency_worker", "research_merger")
    builder.add_edge("visa_worker", "research_merger")
    builder.add_edge("research_merger", END)

    return builder.compile()
