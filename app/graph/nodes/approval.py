from time import perf_counter
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from app.core.logging import get_logger
from app.graph.state import TravelState

logger = get_logger(__name__)


def approval_gate_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, str]:
    """Pass state through to the approval router as a named graph step."""

    thread_id = _get_thread_id(config)
    logger.info("approval gate entered thread_id=%s", thread_id)
    logger.info("approval gate exited thread_id=%s", thread_id)
    return {}


def approval_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, bool | dict[str, Any] | None | str]:
    """Interrupt graph execution until a human approves or rejects the action."""

    started_at = perf_counter()
    thread_id = _get_thread_id(config)
    approval_context = state.get("approval_context") or {}
    action = str(approval_context.get("action", "sensitive_tool_execution"))
    summary = str(
        approval_context.get(
            "summary",
            "Approval is required before continuing.",
        )
    )
    payload = {
        "action": action,
        "summary": summary,
        "context": approval_context,
        "thread_id": thread_id,
    }

    logger.info(
        "interrupt created thread_id=%s action=%s",
        thread_id,
        action,
    )
    resume_value = interrupt(payload)
    approved = _parse_approval(resume_value)

    duration = perf_counter() - started_at
    logger.info(
        "interrupt resumed thread_id=%s action=%s approved=%s duration=%.4fs",
        thread_id,
        action,
        approved,
        duration,
    )

    if approved:
        logger.info("approval accepted thread_id=%s action=%s", thread_id, action)
        return {
            "approval_required": False,
            "approval_context": approval_context,
            "approved": True,
        }

    logger.info("approval rejected thread_id=%s action=%s", thread_id, action)
    return {
        "approval_required": False,
        "approval_context": approval_context,
        "approved": False,
        "response": f"Approval rejected for {action}. I did not execute the requested action.",
    }


def approval_decision_router(
    state: TravelState,
) -> str:
    """Route after approval based on the human decision."""

    if state.get("approved") is True:
        return "tools"

    return "responder"


def _parse_approval(resume_value: Any) -> bool:
    """Parse the human approval decision from a resume payload."""

    if isinstance(resume_value, bool):
        return resume_value

    if isinstance(resume_value, dict):
        return bool(resume_value.get("approved", False))

    return False


def _get_thread_id(config: RunnableConfig) -> str:
    """Extract thread id from RunnableConfig."""

    configurable = config.get("configurable", {})
    return str(configurable.get("thread_id", "unknown"))
