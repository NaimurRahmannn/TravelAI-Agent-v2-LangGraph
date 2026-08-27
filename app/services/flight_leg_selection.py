from typing import Any

from app.core.logging import get_logger
from app.graph.builder import get_graph
from app.models import ConfirmedTripSnapshot, TravelSelections, TripPlan
from app.schemas.api import (
    DetailedRoutingRequest,
    FlightLegSelectionRequest,
    FlightLegSelectionResponse,
)
from app.services.detailed_routing import DetailedRoutingError, DetailedRoutingService
from app.services.travel_selection import (
    TravelSelectionError,
    calculate_trip_cost_summary,
)

logger = get_logger(__name__)


class FlightLegSelectionService:
    """Confirm one independently priced flight leg and refresh derived state."""

    @staticmethod
    async def _get_graph() -> Any:
        return await get_graph()

    async def confirm(
        self,
        request: FlightLegSelectionRequest,
    ) -> FlightLegSelectionResponse:
        graph = await self._get_graph()
        config = {"configurable": {"thread_id": request.thread_id}}
        checkpoint = await graph.aget_state(config)
        values = checkpoint.values if checkpoint is not None else None
        if checkpoint is None or checkpoint.created_at is None or not values:
            raise TravelSelectionError(404, "Travel thread was not found.")
        try:
            itinerary = TripPlan.model_validate(values.get("itinerary"))
            confirmed = ConfirmedTripSnapshot.model_validate(
                values.get("confirmed_snapshot")
            )
        except ValueError as exc:
            raise TravelSelectionError(
                409,
                "Confirm outbound, return, and hotel selections before replacing "
                "one flight leg.",
            ) from exc
        selections = confirmed.selections
        if (
            selections.selected_outbound_flight_id is None
            or selections.selected_return_flight_id is None
        ):
            raise TravelSelectionError(
                409,
                "This trip uses a legacy bundled fare. Re-select separate outbound "
                "and return flights before replacing one leg.",
            )
        candidates = (
            itinerary.recommendations.outbound_flights
            if request.scope == "outbound" and itinerary.recommendations
            else itinerary.recommendations.return_flights
            if itinerary.recommendations
            else []
        )
        selected = next(
            (
                option
                for option in candidates
                if option.provider_offer_id == request.selected_flight_id
            ),
            None,
        )
        if selected is None:
            raise TravelSelectionError(
                409,
                "That flight is no longer available in the current candidates.",
            )
        updates = {
            "selected_outbound_flight_id": request.selected_flight_id
        } if request.scope == "outbound" else {
            "selected_return_flight_id": request.selected_flight_id
        }
        updated_selections = selections.model_copy(update=updates)
        summary = calculate_trip_cost_summary(itinerary, updated_selections)
        updated_snapshot = ConfirmedTripSnapshot(
            revision=confirmed.revision + 1,
            itinerary=itinerary.model_copy(deep=True),
            selections=updated_selections,
            cost_summary=summary,
            routing_plan=None,
        )
        await graph.aupdate_state(
            config,
            {
                "travel_selections": updated_selections,
                "trip_cost_summary": summary,
                "detailed_routing_plan": None,
                "confirmed_snapshot": updated_snapshot,
            },
            as_node="memory_write",
        )
        routing_plan = None
        try:
            routing_response = await DetailedRoutingService().generate(
                DetailedRoutingRequest(thread_id=request.thread_id)
            )
            routing_plan = routing_response.detailed_routing_plan
            updated_snapshot = updated_snapshot.model_copy(
                update={"routing_plan": routing_plan}
            )
        except DetailedRoutingError as exc:
            logger.info(
                "flight_leg_routing_unavailable thread_id=%s detail=%s",
                request.thread_id,
                exc.detail,
            )
        except Exception as exc:
            logger.warning(
                "flight_leg_routing_failed thread_id=%s error_type=%s",
                request.thread_id,
                type(exc).__name__,
            )
        return FlightLegSelectionResponse(
            thread_id=request.thread_id,
            selected_flight=selected,
            itinerary=itinerary,
            travel_selections=updated_selections,
            trip_cost_summary=summary,
            detailed_routing_plan=routing_plan,
            confirmed_snapshot=updated_snapshot,
        )
