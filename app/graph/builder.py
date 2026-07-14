from langgraph.graph import StateGraph,START, END

from app.graph.state import TravelState
from app.graph.nodes.planner import planner_node


builder = StateGraph(TravelState)

builder.add_node("planner",planner_node)
builder.add_edge(START,"planner")
builder.add_edge("planner", END)
graph=builder.compile()

