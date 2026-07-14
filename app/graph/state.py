from typing import TypedDict

from langgraph.graph import MessagesState

class PlannerState(TypedDict):
    current_step: str
    next_action: str

class TravelState(MessagesState):
    planner:PlannerState