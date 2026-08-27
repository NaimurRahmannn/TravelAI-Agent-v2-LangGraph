from time import perf_counter
from typing import Any, cast

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from app.core.logging import get_logger
from app.graph.state import TravelState
from app.models import FlightSearchScope, TripPlan
from app.services.itinerary_renderer import render_flight_recommendations

logger = get_logger(__name__)


def flight_responder_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, Any]:
    """Return only the requested flight suggestions for a flight follow-up."""

    del config
    started_at = perf_counter()
    raw_itinerary = state.get("itinerary")
    try:
        itinerary = TripPlan.model_validate(raw_itinerary)
    except ValueError:
        response = _missing_flight_context_response(state, scope=_validated_scope(
            state.get("flight_search_scope")
        ))
    else:
        scope = _validated_scope(state.get("flight_search_scope"))
        response = render_flight_recommendations(itinerary, scope=scope)

    logger.info(
        "flight_responder_node exited duration=%.4fs",
        perf_counter() - started_at,
    )
    return {
        "response": response,
        "messages": [AIMessage(content=response)],
    }


def _validated_scope(value: object) -> FlightSearchScope:
    if value in {"outbound", "return", "round_trip"}:
        return cast(FlightSearchScope, value)
    return "round_trip"


def _missing_flight_context_response(
    state: TravelState,
    *,
    scope: FlightSearchScope,
) -> str:
    trip = state.get("trip")
    if trip is not None:
        if scope in {"outbound", "round_trip"} and trip.start_date is None:
            return "What departure date should I use for the flight search?"
        if scope in {"return", "round_trip"} and trip.end_date is None:
            return "What return date should I use for the flight search?"
    return (
        "I need a completed trip with an origin, destination, and travel dates "
        "before I can suggest flights."
    )
