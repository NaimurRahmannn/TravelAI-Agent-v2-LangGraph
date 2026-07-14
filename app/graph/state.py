from typing import TypedDict

from langgraph.graph import MessagesState
from app.models import Trip

class PlannerState(TypedDict):
    """State values produced by the planner node."""

    current_step: str
    next_action: str

class TravelState(MessagesState):
    """Shared state passed between travel graph nodes."""

    planner: PlannerState
    trip: Trip | None
    missing_fields: list[str]
    needs_clarification: bool
