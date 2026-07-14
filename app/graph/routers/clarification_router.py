from time import perf_counter
from typing import Literal

from app.core.logging import get_logger
from app.graph.state import TravelState

logger = get_logger(__name__)


def clarification_router(
    state: TravelState,
) -> Literal["clarification", "responder"]:
    """Route to clarification when required trip fields are missing."""

    started_at = perf_counter()
    logger.info(
        "clarification_router entered tool_count=%s tool_names=%s",
        0,
        [],
    )

    if state.get("needs_clarification") or state.get("missing_fields"):
        _log_exit("clarification", started_at)
        return "clarification"

    _log_exit("responder", started_at)
    return "responder"


def _log_exit(
    route: Literal["clarification", "responder"],
    started_at: float,
) -> None:
    """Log clarification routing metadata and duration."""

    duration = perf_counter() - started_at
    logger.info(
        "clarification_router exited route=%s tool_count=%s tool_names=%s duration=%.4fs",
        route,
        0,
        [],
        duration,
    )
