from langgraph.graph import StateGraph,START, END

from app.graph.state import TravelState
from app.graph.nodes.planner import planner_node
from app.graph.nodes.extractor import extractor_node
from app.graph.nodes.responder import responder_node


builder = StateGraph(TravelState)

builder.add_node("planner",planner_node)
builder.add_node("extractor",extractor_node)
builder.add_node("responder",responder_node)

builder.add_edge(START,"planner")
builder.add_edge("planner", "extractor")
builder.add_edge("extractor","responder")
builder.add_edge("responder",END)
graph=builder.compile()

