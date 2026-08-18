import re
from time import perf_counter

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from app.core.logging import get_logger
from app.llm import get_groq_llm
from app.models import Trip, TripExtraction

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
    llm = get_groq_llm()

    chain = (
        extractor_prompt
        | llm.with_structured_output(
            TripExtraction,
            method="json_schema",
            strict=True,
        )
    )

    latest_user_message = _get_latest_human_message(state["messages"])

    extracted_trip = chain.invoke(
        {
            "existing_trip": _format_existing_trip(state.get("trip")),
            "messages": [latest_user_message] if latest_user_message else [],
        },
        config=config,
    )
    extracted_trip = _apply_deterministic_fallback(
        extracted_trip,
        str(latest_user_message.content) if latest_user_message else "",
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

    if not trip.origin:
        missing_fields.append("origin")

    if trip.travelers is None:
        missing_fields.append("travelers")

    return missing_fields


def _merge_trip(
    existing_trip: Trip | None,
    extracted_trip: TripExtraction,
) -> Trip:
    """Merge newly extracted trip details with checkpointed trip state."""

    existing_data = existing_trip.model_dump() if existing_trip else Trip().model_dump()
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


def _apply_deterministic_fallback(
    extracted_trip: TripExtraction,
    message: str,
) -> TripExtraction:
    """Fill obvious facts when a model returns valid but incomplete structured data."""

    updates: dict[str, str | int | float] = {}

    if extracted_trip.duration is None:
        duration_match = re.search(r"\b(\d+)\s*-?\s*days?\b", message, re.IGNORECASE)
        if duration_match:
            updates["duration"] = int(duration_match.group(1))

    if extracted_trip.destination is None:
        destination = _extract_destination(message)
        if destination:
            updates["destination"] = destination

    if extracted_trip.origin is None:
        origin_match = re.search(
            r"\bfrom\s+([a-z][a-z .'-]*?)(?=\s+(?:for|with|on|to)\b|[,!?]|$)",
            message,
            re.IGNORECASE,
        )
        if origin_match:
            updates["origin"] = _normalize_place(origin_match.group(1))

    if extracted_trip.travelers is None:
        travelers = _extract_travelers(message)
        if travelers is not None:
            updates["travelers"] = travelers

    if extracted_trip.budget is None:
        budget, currency = _extract_budget(message)
        if budget is not None:
            updates["budget"] = budget
        if currency and extracted_trip.currency is None:
            updates["currency"] = currency

    if not updates:
        return extracted_trip

    logger.warning(
        "structured extraction required deterministic fallback fields=%s",
        sorted(updates),
    )
    return extracted_trip.model_copy(update=updates)


def _extract_destination(message: str) -> str | None:
    """Extract destinations from common, explicit travel request phrases."""

    patterns = (
        r"\b(?:visit|travel\s+to|go\s+to|going\s+to)\s+"
        r"([a-z][a-z .'-]*?)(?=\s+(?:from|for|with|on)\b|[,!?]|$)",
        r"\b(?:a|an)\s+([a-z][a-z .'-]*?)\s+trip\b",
        r"\btrip\s+to\s+([a-z][a-z .'-]*?)(?=\s+(?:from|for|with|on)\b|[,!?]|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            return _normalize_place(match.group(1))
    return None


def _extract_budget(message: str) -> tuple[float | None, str | None]:
    """Extract an explicitly labelled budget and its written currency."""

    number = r"(?P<amount>\d[\d,]*(?:\.\d+)?)"
    prefix_match = re.search(
        rf"(?P<currency>US\$|\$|€|£|₹|৳|USD|BDT|EUR|GBP|INR)\s*{number}",
        message,
        re.IGNORECASE,
    )
    suffix_match = re.search(
        rf"{number}\s*(?P<currency>USD|dollars?|BDT|taka|tk|EUR|euros?|GBP|pounds?|INR|rupees?)\b",
        message,
        re.IGNORECASE,
    )
    match = prefix_match or suffix_match
    if match:
        amount = float(match.group("amount").replace(",", ""))
        return amount, _normalize_currency(match.group("currency"))

    bare_budget = re.search(
        rf"\bbudget(?:\s+of|\s+is|\s*:)?\s*{number}\b",
        message,
        re.IGNORECASE,
    )
    if bare_budget:
        return float(bare_budget.group("amount").replace(",", "")), None
    return None, None


def _extract_travelers(message: str) -> int | None:
    """Extract an explicitly stated party size from common phrases."""

    if re.search(r"\b(?:solo|just me|travel(?:ing|ling)? alone)\b", message, re.IGNORECASE):
        return 1

    patterns = (
        r"\b(\d+)\s+(?:travelers?|travellers?|people|persons?|adults?)\b",
        r"\bparty\s+of\s+(\d+)\b",
        r"\bfor\s+(\d+)\s+(?:travelers?|travellers?|people|persons?|adults?)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _normalize_place(value: str) -> str:
    """Normalize a place captured from free text."""

    return " ".join(part.capitalize() for part in value.strip().split())


def _normalize_currency(value: str) -> str:
    """Normalize written currency markers to ISO codes."""

    normalized = value.strip().lower()
    if normalized in {"$", "us$", "usd", "dollar", "dollars"}:
        return "USD"
    if normalized in {"৳", "bdt", "taka", "tk"}:
        return "BDT"
    if normalized in {"€", "eur", "euro", "euros"}:
        return "EUR"
    if normalized in {"£", "gbp", "pound", "pounds"}:
        return "GBP"
    if normalized in {"₹", "inr", "rupee", "rupees"}:
        return "INR"
    return value.strip().upper()


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
