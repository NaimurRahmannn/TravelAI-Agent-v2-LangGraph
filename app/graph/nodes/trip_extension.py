from datetime import date, timedelta
from time import perf_counter
from typing import Literal

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from app.core.logging import get_logger
from app.graph.state import TravelState
from app.models import (
    RecommendationDomainState,
    TravelRecommendations,
    TravelSelections,
    Trip,
    TripPlan,
)
from app.services.itinerary_renderer import render_itinerary
from app.services.trip_dates import validate_and_derive_duration

logger = get_logger(__name__)


def trip_extension_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, object]:
    """Apply an explicit relative date mutation while retaining the old plan."""

    del config
    started_at = perf_counter()
    try:
        trip = Trip.model_validate(state.get("trip"))
        base = TripPlan.model_validate(state.get("itinerary"))
        extension_days = int(state.get("extension_days") or 0)
        if extension_days < 1 or extension_days > 30:
            raise ValueError("Extension must be between one and thirty days")
        old_end = trip.end_date or base.end_date
        start_date = trip.start_date or base.start_date
        if old_end is None or start_date is None:
            raise ValueError("Trip dates are required")
        new_end = old_end + timedelta(days=extension_days)
        new_duration = validate_and_derive_duration(start_date, new_end)
        updated_trip = trip.model_copy(
            update={
                "start_date": start_date,
                "end_date": new_end,
                "duration": new_duration,
            }
        )
    except (TypeError, ValueError):
        response = (
            "I need an existing itinerary with exact start and end dates before "
            "I can extend it. Your saved plan has not been changed."
        )
        return {
            "extension_ready": False,
            "response": response,
            "messages": [AIMessage(content=response)],
        }

    logger.info(
        "trip_extension_node old_end=%s new_end=%s extension_days=%s duration=%.4fs",
        old_end,
        new_end,
        extension_days,
        perf_counter() - started_at,
    )
    return {
        "trip": updated_trip,
        "extension_base_trip": trip,
        "extension_base_itinerary": base,
        "extension_original_end_date": old_end,
        "extension_ready": True,
        "flight_search_cache": None,
        "travel_selections": _preserve_valid_hotel_selections(base, state),
        "trip_cost_summary": None,
        "detailed_routing_plan": None,
    }


def extension_router(
    state: TravelState,
) -> Literal["extension_generator", "extension_responder"]:
    return "extension_generator" if state.get("extension_ready") else "extension_responder"


def extension_merge_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, object]:
    """Keep existing days byte-for-byte and accept only newly generated days."""

    del config
    try:
        base = TripPlan.model_validate(state.get("extension_base_itinerary"))
        generated = TripPlan.model_validate(state.get("itinerary"))
        trip = Trip.model_validate(state.get("trip"))
        old_end = state.get("extension_original_end_date")
        if old_end is None or trip.start_date is None or trip.end_date is None:
            raise ValueError("Extension state is incomplete")
        old_duration = base.duration_days
        if generated.duration_days <= old_duration:
            raise ValueError("Generated plan does not contain extension days")
        new_days = generated.days[old_duration:]
        expected_new_count = generated.duration_days - old_duration
        if len(new_days) != expected_new_count:
            raise ValueError("Generated extension days are incomplete")
        recommendations = _recommendations_after_extension(base, old_end)
        merged = generated.model_copy(
            update={
                "origin": trip.origin,
                "destination": trip.destination or generated.destination,
                "start_date": trip.start_date,
                "end_date": trip.end_date,
                "duration_days": trip.duration,
                "travelers": trip.travelers or generated.travelers,
                "preferences": trip.preferences,
                "days": [*base.days, *new_days],
                "recommendations": recommendations,
                "guest_nationality_country_code": (
                    base.guest_nationality_country_code
                ),
            }
        )
    except (TypeError, ValueError):
        logger.warning("extension_merge_failed", exc_info=True)
        response = (
            "I couldn't generate the additional itinerary days, so your original "
            "plan has been kept unchanged."
        )
        base_value = state.get("extension_base_itinerary")
        base_trip = state.get("extension_base_trip")
        return {
            "itinerary": base_value,
            "trip": base_trip,
            "extension_ready": False,
            "response": response,
            "messages": [AIMessage(content=response)],
        }

    return {"itinerary": merged, "extension_ready": True}


def extension_merge_router(
    state: TravelState,
) -> Literal["extension_place", "extension_responder"]:
    return "extension_place" if state.get("extension_ready") else "extension_responder"


def extension_responder_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, object]:
    """Render an extension result or preserve a focused failure response."""

    del config
    if not state.get("extension_ready"):
        return {"response": state.get("response", "")}
    itinerary = TripPlan.model_validate(state.get("itinerary"))
    added_days = state.get("extension_days") or 0
    response = render_itinerary(itinerary)
    message = (
        f"The trip was extended by {added_days} day"
        f"{'s' if added_days != 1 else ''}.\n\n{response}"
    )
    return {"response": message, "messages": [AIMessage(content=message)]}


def _recommendations_after_extension(
    base: TripPlan,
    old_end: date,
) -> TravelRecommendations:
    recommendations = (
        base.recommendations.model_copy(deep=True)
        if base.recommendations is not None
        else TravelRecommendations()
    )
    recommendations.flights = []
    recommendations.flight_status = RecommendationDomainState()
    recommendations.hotels = [
        hotel for hotel in recommendations.hotels if hotel.check_out <= old_end
    ]
    recommendations.hotel_status = RecommendationDomainState()
    return recommendations


def _preserve_valid_hotel_selections(
    base: TripPlan,
    state: TravelState,
) -> TravelSelections | None:
    try:
        selections = TravelSelections.model_validate(state.get("travel_selections"))
    except ValueError:
        return None
    old_end = base.end_date
    recommendations = base.recommendations
    if old_end is None or recommendations is None:
        return None
    valid_ids = {
        hotel.provider_offer_id
        for hotel in recommendations.hotels
        if hotel.check_out <= old_end
    }
    hotels = [
        selection
        for selection in selections.selected_hotels
        if selection.hotel_option_id in valid_ids
    ]
    return TravelSelections(selected_hotels=hotels) if hotels else None
