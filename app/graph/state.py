from datetime import date
from typing import Annotated, Literal, TypedDict

from langgraph.graph import MessagesState
from app.models import (
    DetailedRoutingPlan,
    FlightSearchCache,
    FlightSearchScope,
    TravelSelections,
    Trip,
    TripCostSummary,
    TripPlan,
    TurnDecision,
    TurnIntent,
)


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


class PlannerState(TypedDict):
    """State values produced by the planner node."""

    current_step: str
    next_action: str


class TravelState(MessagesState):
    """Shared state passed between travel graph nodes."""

    user_id: str | None
    planner: PlannerState
    turn_intent: TurnIntent
    turn_decision: TurnDecision
    trip: Trip | None
    preferences_changed: bool
    selected_start_date: date | None
    selected_end_date: date | None
    itinerary: TripPlan | None
    flight_search_cache: FlightSearchCache | None
    flight_search_scope: FlightSearchScope | None
    extension_days: int | None
    extension_original_end_date: date | None
    extension_base_trip: Trip | None
    extension_base_itinerary: TripPlan | None
    extension_ready: bool
    travel_selections: TravelSelections | None
    trip_cost_summary: TripCostSummary | None
    detailed_routing_plan: DetailedRoutingPlan | None
    missing_fields: list[str]
    needs_clarification: bool
    research_results: Annotated[dict[str, str], merge_research_results]
    approval_required: bool
    approval_context: dict | None
    approved: bool | None
    response: str
    long_term_memories: list[str]
