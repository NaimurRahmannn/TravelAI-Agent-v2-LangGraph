from typing import Annotated, TypedDict

from langgraph.graph import MessagesState
from app.models import Trip


def merge_research_results(
    left: dict[str, str] | None,
    right: dict[str, str] | None,
) -> dict[str, str]:
    """Merge parallel research result updates without overwriting unrelated keys."""

    merged: dict[str, str] = {}
    if left:
        merged.update(left)
    if right:
        merged.update(right)
    return merged


def merge_pending_tasks(
    left: list[str] | None,
    right: list[str] | None,
) -> list[str]:
    """Merge pending research task names while preserving insertion order."""

    merged: list[str] = []
    for task in (left or []) + (right or []):
        if task not in merged:
            merged.append(task)
    return merged


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
    research_results: Annotated[dict[str, str], merge_research_results]
    pending_tasks: Annotated[list[str], merge_pending_tasks]
