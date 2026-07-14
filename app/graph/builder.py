from typing import Any

from langgraph.graph import END, START, StateGraph

from app.graph.nodes.clarification import clarification_node
from app.graph.nodes.extractor import extractor_node
from app.graph.nodes.planner import planner_node
from app.graph.nodes.responder import responder_node
from app.graph.routers.clarification_router import clarification_router
from app.graph.state import TravelState


def build_graph() -> Any:
    """Build and compile the travel planning graph."""

    builder = StateGraph(TravelState)

    builder.add_node("planner", planner_node)
    builder.add_node("extractor", extractor_node)
    builder.add_node("clarification", clarification_node)
    builder.add_node("responder", responder_node)

    builder.add_edge(START, "planner")
    builder.add_edge("planner", "extractor")
    builder.add_conditional_edges(
        "extractor",
        clarification_router,
        {
            "clarification": "clarification",
            "responder": "responder",
        },
    )
    builder.add_edge("clarification", END)
    builder.add_edge("responder", END)

    return builder.compile()
