from typing import Literal

from app.core.logging import get_logger
from app.graph.state import TravelState

logger = get_logger(__name__)


def clarification_router(
    state: TravelState,
) -> Literal["clarification", "responder"]:
    """Route to clarification when required trip fields are missing."""

    logger.info("clarification_router started")

    if state.get("needs_clarification") or state.get("missing_fields"):
        logger.info("clarification_router finished: clarification")
        return "clarification"

    logger.info("clarification_router finished: responder")
    return "responder"
