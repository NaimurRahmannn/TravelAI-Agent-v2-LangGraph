from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.core.logging import get_logger
from app.graph.builder import get_graph
from app.models import (
    FlightOption,
    HotelOption,
    TravelSelections,
    TripCostSummary,
    TripPlan,
)
from app.schemas.api import TravelSelectionRequest, TravelSelectionResponse
from app.services.hotel_recommendation import (
    MAX_HOTEL_STAY_SEARCHES,
    derive_hotel_stays,
)

logger = get_logger(__name__)
_MONEY_QUANTUM = Decimal("0.01")
_STALE_SELECTION_DETAIL = (
    "These recommendations are no longer available for the current trip. "
    "Please use the latest trip recommendations."
)


class TravelSelectionError(ValueError):
    """A deterministic client error while validating stored recommendations."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class TravelSelectionService:
    """Persist validated snapshot selections without calling any provider."""

    @staticmethod
    async def _get_graph() -> Any:
        return await get_graph()

    async def confirm(
        self,
        request: TravelSelectionRequest,
    ) -> TravelSelectionResponse:
        graph = await self._get_graph()
        config = {"configurable": {"thread_id": request.thread_id}}
        snapshot = await graph.aget_state(config)
        values = snapshot.values if snapshot is not None else None
        if snapshot is None or snapshot.created_at is None or not values:
            raise TravelSelectionError(404, "Travel thread was not found.")

        raw_itinerary = values.get("itinerary")
        if raw_itinerary is None:
            raise TravelSelectionError(
                409,
                "The travel thread does not have a completed itinerary.",
            )
        try:
            itinerary = TripPlan.model_validate(raw_itinerary)
        except ValueError as exc:
            raise TravelSelectionError(
                409,
                "The travel thread does not have a usable itinerary.",
            ) from exc

        selections = TravelSelections(
            selected_flight_id=request.selected_flight_id,
            selected_hotels=request.selected_hotels,
        )
        summary = calculate_trip_cost_summary(itinerary, selections)

        await graph.aupdate_state(
            config,
            {
                "travel_selections": selections,
                "trip_cost_summary": summary,
            },
            as_node="memory_write",
        )
        logger.info(
            "travel_selection_confirmed thread_id=%s flight_id=%s "
            "hotel_stay_count=%s updated_total_usd=%.2f",
            request.thread_id,
            selections.selected_flight_id,
            len(selections.selected_hotels),
            summary.updated_trip_total_usd,
        )
        return TravelSelectionResponse(
            thread_id=request.thread_id,
            travel_selections=selections,
            trip_cost_summary=summary,
        )


def calculate_trip_cost_summary(
    trip_plan: TripPlan,
    selections: TravelSelections,
) -> TripCostSummary:
    """Resolve stored IDs and calculate a complete USD summary with Decimal."""

    selected_flight, selected_hotels = validate_travel_selections(
        trip_plan,
        selections,
    )
    currencies = {
        selected_flight.currency,
        *(hotel.currency for hotel in selected_hotels),
    }
    if currencies != {"USD"}:
        raise TravelSelectionError(
            409,
            "The updated trip total cannot be calculated because a selected "
            "option is not priced in USD.",
        )

    base_total = _money(trip_plan.budget.estimated_total_usd)
    flight_total = _money(selected_flight.total_price)
    hotel_total = sum(
        (_money(hotel.total_price) for hotel in selected_hotels),
        start=Decimal("0.00"),
    ).quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    additions = (flight_total + hotel_total).quantize(
        _MONEY_QUANTUM,
        rounding=ROUND_HALF_UP,
    )
    updated_total = (base_total + additions).quantize(
        _MONEY_QUANTUM,
        rounding=ROUND_HALF_UP,
    )
    user_budget = (
        _money(trip_plan.budget.user_budget_usd)
        if trip_plan.budget.user_budget_usd is not None
        else None
    )
    difference = (
        (updated_total - user_budget).quantize(
            _MONEY_QUANTUM,
            rounding=ROUND_HALF_UP,
        )
        if user_budget is not None
        else None
    )
    return TripCostSummary(
        base_trip_total_usd=float(base_total),
        selected_flight_usd=float(flight_total),
        selected_hotels_usd=float(hotel_total),
        additions_total_usd=float(additions),
        updated_trip_total_usd=float(updated_total),
        user_budget_usd=float(user_budget) if user_budget is not None else None,
        difference_from_budget_usd=(
            float(difference) if difference is not None else None
        ),
    )


def validate_travel_selections(
    trip_plan: TripPlan,
    selections: TravelSelections,
) -> tuple[FlightOption, list[HotelOption]]:
    """Resolve a complete IDs-only selection against the current snapshot."""

    recommendations = trip_plan.recommendations
    if (
        recommendations is None
        or recommendations.flight_status.status != "available"
        or recommendations.hotel_status.status != "available"
    ):
        raise TravelSelectionError(409, _STALE_SELECTION_DETAIL)

    flights = [
        option
        for option in recommendations.flights
        if option.provider_offer_id == selections.selected_flight_id
    ]
    if len(flights) != 1:
        logger.info(
            "travel_selection_invalid flight_id=%s",
            selections.selected_flight_id,
        )
        raise TravelSelectionError(409, _STALE_SELECTION_DETAIL)

    required_stays = derive_hotel_stays(trip_plan)[:MAX_HOTEL_STAY_SEARCHES]
    required_keys = {stay.stay_key for stay in required_stays}
    submitted_keys = {selection.stay_key for selection in selections.selected_hotels}
    if not required_keys or submitted_keys != required_keys:
        raise TravelSelectionError(
            409,
            "Select one hotel for every required stay before confirming.",
        )

    selected_hotels: list[HotelOption] = []
    for selection in selections.selected_hotels:
        matches = [
            option
            for option in recommendations.hotels
            if option.provider_offer_id == selection.hotel_option_id
            and option.stay_key == selection.stay_key
        ]
        if len(matches) != 1:
            logger.info(
                "travel_selection_invalid hotel_option_id=%s stay_key=%s",
                selection.hotel_option_id,
                selection.stay_key,
            )
            raise TravelSelectionError(409, _STALE_SELECTION_DETAIL)
        selected_hotels.append(matches[0])

    return flights[0], selected_hotels


def _money(value: float) -> Decimal:
    return Decimal(str(value)).quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)
