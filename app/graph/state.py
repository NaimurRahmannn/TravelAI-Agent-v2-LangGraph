from typing import TypedDict

from langgraph.graph import MessagesState
from app.models import Trip

class PlannerState(TypedDict):
    current_step: str
    next_action: str

class TravelState(MessagesState):
    planner:PlannerState
    trip:Trip|None