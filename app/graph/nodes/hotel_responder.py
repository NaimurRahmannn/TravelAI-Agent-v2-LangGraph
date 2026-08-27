from time import perf_counter

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from app.core.logging import get_logger
from app.graph.state import TravelState
from app.models import TripPlan
from app.services.itinerary_renderer import render_hotel_recommendations

logger = get_logger(__name__)


def hotel_responder_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, object]:
    """Return hotel-only suggestions without replacing itinerary days or flights."""

    del config
    started_at = perf_counter()
    try:
        itinerary = TripPlan.model_validate(state.get("itinerary"))
    except ValueError:
        response = (
            "I need a completed trip with travel dates before I can suggest hotels."
        )
    else:
        response = render_hotel_recommendations(itinerary)

    logger.info(
        "hotel_responder_node exited duration=%.4fs",
        perf_counter() - started_at,
    )
    return {
        "response": response,
        "messages": [AIMessage(content=response)],
    }
