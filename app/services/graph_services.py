from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from app.core.logging import get_logger
from app.graph.builder import get_graph
from app.models import ConfirmedTripSnapshot, TravelSelections, TripPlan
from app.schemas.approval import ApprovalRequest, ApprovalResponse
from app.schemas.api import ChatRequest, ChatResponse
from app.services.selection_status import build_travel_selection_status

logger = get_logger(__name__)


class GraphService:
    """Application service responsible for invoking the graph."""

    def __init__(self) -> None:
        """Construct the service. The compiled graph is fetched lazily.

        get_graph() is async (AsyncSqliteSaver needs a running event loop
        to open its connection), so it can't be resolved here in a plain
        __init__. Each call below awaits self._get_graph() instead, which
        builds the graph once on first use and reuses it after that.
        """

    @staticmethod
    async def _get_graph() -> Any:
        """Return the shared compiled graph, building it on first use."""

        return await get_graph()

    def invoke(self, request: ChatRequest) -> ChatResponse:
        """Synchronous invocation is not supported.

        The graph is compiled with AsyncSqliteSaver, which only implements
        the async checkpoint API (mirroring the original bug in reverse:
        AsyncSqliteSaver.get_state()/.invoke() raise, only the a-prefixed
        methods work). Nothing in this app's routes calls this method; use
        ainvoke instead.
        """

        raise HTTPException(
            status_code=501,
            detail="Synchronous graph execution isn't supported with the "
            "async SQLite checkpointer. Use ainvoke instead.",
        )

    async def ainvoke(self, request: ChatRequest) -> ChatResponse:
        """Invoke the travel graph asynchronously and return a typed response."""

        thread_id = self.resolve_thread_id(request.thread_id)
        config = self.build_config(thread_id)

        try:
            graph = await self._get_graph()
            logger.info("checkpoint load thread_id=%s", thread_id)
            await graph.aget_state(config)
            logger.info("graph async invocation started thread_id=%s", thread_id)

            result = await graph.ainvoke(
                self.build_input(request),
                config=config,
            )
            if "__interrupt__" in result:
                return ChatResponse(
                    response="Approval required before continuing.",
                    thread_id=thread_id,
                    itinerary=None,
                    missing_fields=[],
                )

            logger.info("checkpoint save thread_id=%s", thread_id)
            await graph.aget_state(config)
            logger.info("graph async invocation finished thread_id=%s", thread_id)
            raw_itinerary = result.get("itinerary")
            itinerary = (
                TripPlan.model_validate(raw_itinerary)
                if raw_itinerary is not None
                else None
            )
            raw_selections = result.get("travel_selections")
            selections = (
                TravelSelections.model_validate(raw_selections)
                if raw_selections is not None
                else None
            )
            selection_status = build_travel_selection_status(itinerary, selections)
            raw_confirmed_snapshot = result.get("confirmed_snapshot")
            try:
                confirmed_snapshot = ConfirmedTripSnapshot.model_validate(
                    raw_confirmed_snapshot
                )
            except ValueError:
                confirmed_snapshot = None
            turn_intent = result.get("turn_intent")
            is_flight_follow_up = turn_intent in {
                "suggest_outbound_flights",
                "suggest_return_flights",
                "suggest_round_trip_flights",
            }
            is_hotel_follow_up = turn_intent == "suggest_hotels"
            is_extension = turn_intent == "extend_trip"
            extension_succeeded = is_extension and result.get("extension_ready") is True
            is_text_only = turn_intent in {"answer_question", "unsupported"} or (
                is_extension and not extension_succeeded
            )
            response_mode = (
                "flight_suggestions"
                if is_flight_follow_up
                else "hotel_suggestions"
                if is_hotel_follow_up
                else "trip_extension"
                if extension_succeeded and itinerary is not None
                else "unsupported"
                if turn_intent == "unsupported"
                else "text"
                if is_text_only
                else "itinerary"
                if itinerary is not None
                else "text"
            )
            return ChatResponse(
                response=result.get("response", ""),
                response_mode=response_mode,
                flight_search_scope=(
                    result.get("flight_search_scope")
                    if is_flight_follow_up
                    else None
                ),
                thread_id=thread_id,
                # The frontend uses response_mode to render only the shared
                # flight-card component for a focused flight response.
                itinerary=None if is_text_only else itinerary,
                travel_selections=selections,
                trip_cost_summary=result.get("trip_cost_summary"),
                detailed_routing_plan=result.get("detailed_routing_plan"),
                confirmed_snapshot=confirmed_snapshot,
                flight_selection_status=(
                    "not_required"
                    if is_hotel_follow_up or is_text_only
                    else selection_status.flight
                ),
                hotel_selection_status=(
                    "not_required"
                    if is_flight_follow_up or is_text_only
                    else selection_status.hotel
                ),
                missing_fields=result.get("missing_fields", []),
            )
        except Exception as exc:
            logger.exception("Async graph invocation failed thread_id=%s", thread_id)
            raise HTTPException(
                status_code=500,
                detail="Failed to process chat request.",
            ) from exc

    def resume(self, request: ApprovalRequest) -> ApprovalResponse:
        """Synchronous resume is not supported; see invoke() docstring."""

        raise HTTPException(
            status_code=501,
            detail="Synchronous graph execution isn't supported with the "
            "async SQLite checkpointer. Use aresume instead.",
        )

    async def aresume(self, request: ApprovalRequest) -> ApprovalResponse:
        """Resume an interrupted graph asynchronously after human approval."""

        started_at = perf_counter()
        config = self.build_config(request.thread_id)

        try:
            logger.info(
                "interrupt resumed thread_id=%s approved=%s",
                request.thread_id,
                request.approved,
            )
            graph = await self._get_graph()
            await graph.ainvoke(
                Command(
                    resume={
                        "approved": request.approved,
                    }
                ),
                config=config,
            )
            duration = perf_counter() - started_at
            logger.info(
                "resume duration thread_id=%s approved=%s duration=%.4fs",
                request.thread_id,
                request.approved,
                duration,
            )
            return ApprovalResponse(
                status="accepted" if request.approved else "rejected",
                thread_id=request.thread_id,
            )
        except Exception as exc:
            logger.exception("Async graph resume failed thread_id=%s", request.thread_id)
            raise HTTPException(
                status_code=500,
                detail="Failed to resume chat request.",
            ) from exc

    @staticmethod
    def resolve_thread_id(thread_id: str | None) -> str:
        """Return the provided thread id or generate a new UUID."""

        return thread_id or str(uuid4())

    @staticmethod
    def build_config(thread_id: str) -> RunnableConfig:
        """Build the LangGraph runnable config for a conversation thread."""

        return {
            "configurable": {
                "thread_id": thread_id,
            },
        }

    @staticmethod
    def build_input(request: ChatRequest) -> dict[str, Any]:
        """Build the graph input from an API chat request."""

        return {
            "messages": [
                HumanMessage(content=request.message),
            ],
            "user_id": request.user_id,
            "selected_start_date": request.start_date,
            "selected_end_date": request.end_date,
        }
