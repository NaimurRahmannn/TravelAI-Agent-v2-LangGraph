from time import perf_counter
from typing import Literal

from app.core.logging import get_logger
from app.graph.state import TravelState

logger = get_logger(__name__)


def approval_router(
    state: TravelState,
) -> Literal["approval", "tools"]:
    """Route sensitive tool requests through the human approval node."""

    started_at = perf_counter()
    approval_required = bool(state.get("approval_required"))
    approval_context = state.get("approval_context") or {}
    action = approval_context.get("action", "none")
    logger.info(
        "approval_router entered approval_required=%s action=%s",
        approval_required,
        action,
    )

    if approval_required:
        _log_exit("approval", started_at, action)
        return "approval"

    _log_exit("tools", started_at, action)
    return "tools"


def _log_exit(
    route: Literal["approval", "tools"],
    started_at: float,
    action: object,
) -> None:
    """Log the approval route and duration."""

    duration = perf_counter() - started_at
    logger.info(
        "approval_router exited route=%s action=%s duration=%.4fs",
        route,
        action,
        duration,
    )
