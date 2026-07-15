from time import perf_counter

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from app.core.logging import get_logger
from app.llm import get_llm
from app.models import Trip

from app.graph.prompts.extractor import extractor_prompt
from app.graph.state import TravelState
from app.services.currency_converter import convert_to_usd

logger = get_logger(__name__)


def extractor_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, Trip | list[str] | bool]:
    """Extract structured trip details from the latest user message."""

    started_at = perf_counter()
    logger.info(
        "extractor_node entered tool_count=%s tool_names=%s",
        0,
        [],
    )
    llm = get_llm()

    chain = (
        extractor_prompt
        | llm.with_structured_output(Trip)
    )

    latest_user_message = _get_latest_human_message(state["messages"])

    extracted_trip = chain.invoke(
        {
            "existing_trip": _format_existing_trip(state.get("trip")),
            "messages": [latest_user_message] if latest_user_message else [],
        },
        config=config,
    )

    trip = _merge_trip(
        existing_trip=state.get("trip"),
        extracted_trip=extracted_trip,
    )
    trip = _normalize_budget_to_usd(trip)

    missing_fields = _get_missing_required_fields(trip)
    result = {
        "trip": trip,
        "missing_fields": missing_fields,
        "needs_clarification": len(missing_fields) > 0,
    }
    duration = perf_counter() - started_at
    logger.info(
        "extractor_node exited tool_count=%s tool_names=%s duration=%.4fs",
        0,
        [],
        duration,
    )
    return result


def _get_latest_human_message(messages: list[BaseMessage]) -> HumanMessage | None:
    """Return the most recent human message, if any."""

    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message

    return None


def _get_missing_required_fields(trip: Trip) -> list[str]:
    """Return required trip fields that were not extracted."""

    missing_fields: list[str] = []

    if not trip.destination:
        missing_fields.append("destination")

    if trip.budget is None:
        missing_fields.append("budget")

    if trip.duration is None:
        missing_fields.append("duration")

    return missing_fields


def _merge_trip(
    existing_trip: Trip | None,
    extracted_trip: Trip,
) -> Trip:
    """Merge newly extracted trip details with checkpointed trip state."""

    if existing_trip is None:
        return extracted_trip

    existing_data = existing_trip.model_dump()
    extracted_data = extracted_trip.model_dump()
    merged_data = existing_data.copy()

    for field_name, value in extracted_data.items():
        if field_name == "preferences":
            merged_data[field_name] = _merge_preferences(
                existing_data.get(field_name, []),
                value or [],
            )
            continue

        if value is not None:
            merged_data[field_name] = value

    return Trip(**merged_data)


def _merge_preferences(
    existing_preferences: list[str],
    extracted_preferences: list[str],
) -> list[str]:
    """Merge preference lists while preserving order."""

    merged_preferences: list[str] = []
    for preference in existing_preferences + extracted_preferences:
        normalized_preference = preference.strip()
        if normalized_preference and normalized_preference not in merged_preferences:
            merged_preferences.append(normalized_preference)

    return merged_preferences


def _format_existing_trip(trip: Trip | None) -> str:
    """Format an existing trip for the extractor prompt."""

    if trip is None:
        return "None"

    return trip.model_dump_json()


def _normalize_budget_to_usd(trip: Trip) -> Trip:
    """Convert a stated budget into USD so downstream math is consistent."""

    if trip.budget is None or not trip.currency:
        return trip

    code = trip.currency.strip().upper()
    if code in ("USD", "US$", "$"):
        return trip

    converted_budget = convert_to_usd(trip.budget, code)
    if converted_budget is None:
        # Live rate unavailable (bad code, network hiccup, etc.) — keep the
        # original figure rather than guessing at a rate.
        logger.warning("no exchange rate available for currency=%s", code)
        return trip

    return trip.model_copy(
        update={
            "budget_original": trip.budget,
            "budget": converted_budget,
        }
    )