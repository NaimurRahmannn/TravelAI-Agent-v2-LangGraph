from app.models import SelectionStatus, TravelSelections, TravelSelectionStatus, TripPlan
from app.services.hotel_recommendation import derive_hotel_stays


def build_travel_selection_status(
    itinerary: TripPlan | None,
    selections: TravelSelections | None,
) -> TravelSelectionStatus:
    """Derive selection requirements from trusted recommendation state."""

    if itinerary is None:
        return TravelSelectionStatus()
    recommendations = itinerary.recommendations
    selected_flight = bool(
        selections is not None and selections.selected_flight_id is not None
    )
    selected_hotels = bool(selections is not None and selections.selected_hotels)
    if recommendations is None:
        return TravelSelectionStatus(
            flight="selected" if selected_flight else "not_required",
            hotel="selected" if selected_hotels else "not_required",
        )

    flight = _recommendation_selection_status(
        recommendations.flight_status.status,
        has_complete_options=bool(recommendations.flights),
    )

    required_stays = derive_hotel_stays(itinerary)
    required_stay_keys = {stay.stay_key for stay in required_stays}
    option_stay_keys = {hotel.stay_key for hotel in recommendations.hotels}
    hotel_options_complete = bool(required_stay_keys) and (
        required_stay_keys <= option_stay_keys
    )
    hotel = _recommendation_selection_status(
        recommendations.hotel_status.status,
        has_complete_options=hotel_options_complete,
    )
    if selections is not None:
        if selected_flight:
            flight = "selected"
        if selected_hotels:
            selected_stay_keys = {
                selection.stay_key for selection in selections.selected_hotels
            }
            hotel = (
                "selected"
                if required_stay_keys and required_stay_keys <= selected_stay_keys
                else "required"
            )
    return TravelSelectionStatus(flight=flight, hotel=hotel)


def _recommendation_selection_status(
    recommendation_status: str,
    *,
    has_complete_options: bool,
) -> SelectionStatus:
    if recommendation_status == "available" and has_complete_options:
        return "required"
    if recommendation_status in {"available", "no_results", "unavailable"}:
        return "unavailable"
    return "not_required"
