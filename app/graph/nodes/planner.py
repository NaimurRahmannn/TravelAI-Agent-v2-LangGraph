import re
from time import perf_counter
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from app.core.logging import get_logger
from app.graph.state import TravelState
from app.llm import get_groq_llm
from app.models import ChangedTripField, FlightSearchScope, TurnDecision, TurnIntent

logger = get_logger(__name__)


def planner_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, object]:
    """Plan the next graph action for the travel request."""

    started_at = perf_counter()
    logger.info(
        "planner_node entered tool_count=%s tool_names=%s",
        0,
        [],
    )
    latest_message = _latest_user_message(state)
    has_itinerary = state.get("itinerary") is not None
    decision = _classify_turn(
        latest_message,
        has_itinerary=has_itinerary,
        is_clarification_reply=bool(
            state.get("needs_clarification") or state.get("missing_fields")
        ),
        config=config,
    )
    next_action = _action_for_intent(decision.intent)
    result: dict[str, object] = {
        "planner": {
            "current_step": "Planning",
            "next_action": next_action,
        },
        "turn_intent": decision.intent,
        "turn_decision": decision,
        # Always replace a checkpointed scope so a later itinerary turn returns
        # to the default round-trip enrichment behavior.
        "flight_search_scope": decision.flight_scope,
        "extension_days": decision.extension_days,
        "extension_base_itinerary": None,
        "extension_base_trip": None,
        "extension_original_end_date": None,
        "extension_ready": False,
    }
    duration = perf_counter() - started_at
    logger.info(
        "planner_node exited next_action=%s turn_intent=%s duration=%.4fs",
        next_action,
        decision.intent,
        duration,
    )
    return result


def _flight_intent(flight_scope: FlightSearchScope) -> TurnIntent:
    if flight_scope == "outbound":
        return "suggest_outbound_flights"
    if flight_scope == "return":
        return "suggest_return_flights"
    if flight_scope == "round_trip":
        return "suggest_round_trip_flights"
    return "suggest_round_trip_flights"


def planner_router(
    state: TravelState,
) -> Literal[
    "extractor",
    "flight_followup",
    "hotel_followup",
    "question_responder",
    "unsupported_responder",
    "trip_extension",
]:
    """Route each intent without treating an unknown turn as a mutation."""

    intent = state.get("turn_intent", "answer_question")
    if intent in {
        "suggest_outbound_flights",
        "suggest_return_flights",
        "suggest_round_trip_flights",
    }:
        return "flight_followup"
    if intent == "suggest_hotels":
        return "hotel_followup"
    if intent == "extend_trip":
        return "trip_extension"
    if intent == "unsupported":
        return "unsupported_responder"
    if intent == "answer_question":
        return "question_responder"
    return "extractor"


def _latest_user_message(state: TravelState) -> str:
    for message in reversed(state.get("messages", [])):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


def _classify_flight_search_scope(message: str) -> FlightSearchScope | None:
    """Classify explicit flight-shopping follow-ups without another LLM call."""

    normalized = " ".join(message.casefold().split())
    if not re.search(r"\b(?:flight|flights|airfare|airlines?)\b", normalized):
        return None

    shopping_language = re.search(
        r"\b(?:suggest|suggestion|suggestions|recommend|recommendation|"
        r"recommendations|show|see|find|search|refresh|option|options|available|"
        r"cheapest|best|book|booking|need|want|looking)\b",
        normalized,
    )
    scoped_language = re.search(
        r"\b(?:departure|departing|outbound|return|returning|inbound|round[ -]?trip|"
        r"one[ -]?way)\b",
        normalized,
    )
    if shopping_language is None and scoped_language is None:
        return None

    has_outbound = bool(
        re.search(r"\b(?:departure|departing|outbound|one[ -]?way)\b", normalized)
    )
    has_return = bool(
        re.search(r"\b(?:return|returning|inbound|flight back)\b", normalized)
    )
    has_round_trip = bool(re.search(r"\bround[ -]?trip\b", normalized))

    if has_round_trip or (has_outbound and has_return):
        return "round_trip"
    if has_return:
        return "return"
    if has_outbound:
        return "outbound"
    return "round_trip"


def _classify_turn(
    message: str,
    *,
    has_itinerary: bool,
    is_clarification_reply: bool = False,
    config: RunnableConfig,
) -> TurnDecision:
    """Classify a turn with safe deterministic rules and a structured fallback."""

    normalized = " ".join(message.casefold().split())
    flight_scope = _classify_flight_search_scope(message)
    if flight_scope is not None:
        return _decision(
            intent=_flight_intent(flight_scope),
            flight_scope=flight_scope,
        )

    extension_days = _extract_extension_days(normalized)
    if extension_days is not None:
        return _decision(
            intent="extend_trip" if has_itinerary else "answer_question",
            extension_days=extension_days if has_itinerary else None,
            changed_fields=["dates", "duration"] if has_itinerary else [],
            refresh_hotels=_requests_hotels(normalized),
        )

    if _requests_hotels(normalized):
        return _decision(intent="suggest_hotels", refresh_hotels=True)

    if is_clarification_reply and not _is_question(normalized):
        return _decision(intent="modify_trip" if has_itinerary else "create_trip")

    if _is_explicit_trip_creation(normalized):
        return _decision(intent="create_trip")

    changed_fields = _explicit_changed_fields(normalized)
    if changed_fields:
        return _decision(
            intent="modify_trip" if has_itinerary else "create_trip",
            changed_fields=changed_fields,
        )

    if _is_question(normalized) or not _needs_structured_classification(normalized):
        return _decision(intent="answer_question")

    return _classify_ambiguous_turn(
        message,
        has_itinerary=has_itinerary,
        config=config,
    )


def _extract_extension_days(message: str) -> int | None:
    number_words = {
        "one": "1",
        "two": "2",
        "three": "3",
        "four": "4",
        "five": "5",
        "six": "6",
        "seven": "7",
        "eight": "8",
        "nine": "9",
        "ten": "10",
    }
    for word, number in number_words.items():
        message = re.sub(rf"\b{word}\b", number, message)
    patterns = (
        r"\b(?:extend|extand)(?:\s+(?:my|the|this))?\s+"
        r"(?:trip|travel(?:\s+plan)?|plan|itinerary)"
        r"\s*(?:by|for)?\s*(\d{1,2})\s+(?:(?:more|extra)\s+)?days?"
        r"(?:\s+(?:more|extra))?\b",
        r"\badd\s+(\d{1,2})\s+(?:more|extra)\s+days?\b",
        r"\badd\s+(\d{1,2})\s+days?\b",
        r"\b(\d{1,2})\s+(?:(?:more|extra)\s+days?|days?\s+(?:more|extra))\b",
    )
    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            days = int(match.group(1))
            return days if 1 <= days <= 30 else None
    return None


def _requests_hotels(message: str) -> bool:
    if re.search(r"\b(?:hotel|hotels|accommodation|lodging|resort|hostel)s?\b", message) is None:
        return False
    return re.search(
        r"\b(?:suggest|recommend|recommendation|recommendations|show|find|"
        r"search|refresh|option|options|"
        r"available|best|cheapest|need|want|looking)\b",
        message,
    ) is not None


def _is_explicit_trip_creation(message: str) -> bool:
    planned_trip = re.search(
        r"\b(?:plan|create|build|make|design|organize)\b.{0,30}"
        r"\b(?:trip|itinerary|vacation|holiday|travel plan)\b",
        message,
    )
    stated_travel = re.search(
        r"\b(?:i|we)\s+(?:want|would like|'d like)\s+to\s+"
        r"(?:visit|travel to|go to)\b",
        message,
    )
    return planned_trip is not None or stated_travel is not None


def _explicit_changed_fields(message: str) -> list[ChangedTripField]:
    if re.search(
        r"\b(?:change|update|replace|switch|set|remove|add|prefer|select(?:ed)?|"
        r"choose|chose|instead|"
        r"make it|move|reschedule|increase|decrease)\b",
        message,
    ) is None:
        return []
    field_patterns: dict[ChangedTripField, str] = {
        "origin": r"\b(?:origin|departure city|depart from|leaving from)\b",
        "destination": r"\b(?:destination|travel to|go to|visit instead)\b",
        "dates": r"\b(?:date|dates|start|end|earlier|later|reschedule)\b",
        "duration": r"\b(?:duration|day|days|week|weeks|longer|shorter)\b",
        "budget": r"\b(?:budget|cost|spend|usd|dollar|taka|bdt)\b",
        "travelers": r"\b(?:traveler|travelers|people|person|adult|adults|guest|guests)\b",
        "preferences": (
            r"\b(?:prefer|preferences?|temples?|food|nature|mountains?|rivers?|"
            r"museums?|shopping|nightlife|beaches?|history|culture|relaxing|"
            r"adventure)\b"
        ),
        "activities": r"\b(?:activity|activities|itinerary|place|places|visit|replace|remove)\b",
    }
    return [field for field, pattern in field_patterns.items() if re.search(pattern, message)]


def _is_question(message: str) -> bool:
    return bool(
        message.endswith("?")
        or re.match(
            r"^(?:what|why|how|when|where|who|which|is|are|do|does|did|"
            r"can|could|would|should|will|explain|tell me)\b",
            message,
        )
    )


def _needs_structured_classification(message: str) -> bool:
    return re.search(
        r"\b(?:trip|travel|itinerary|destination|budget|date|days?|hotel|"
        r"flight|activity|activities|visit|vacation|holiday)\b",
        message,
    ) is not None


def _classify_ambiguous_turn(
    message: str,
    *,
    has_itinerary: bool,
    config: RunnableConfig,
) -> TurnDecision:
    try:
        structured = get_groq_llm().with_structured_output(
            TurnDecision,
            method="json_schema",
            strict=True,
        )
        decision = structured.invoke(
            [
                SystemMessage(
                    content=(
                        "Classify only the latest travel-chat turn. Unknown, "
                        "informational, or uncertain requests must be "
                        "answer_question, never modify_trip. Use modify_trip only "
                        "for an explicit mutation. Use unsupported only for a "
                        "clearly requested action outside this travel assistant. "
                        f"A saved itinerary exists: {has_itinerary}."
                    )
                ),
                HumanMessage(content=message),
            ],
            config=config,
        )
        return TurnDecision.model_validate(decision)
    except Exception as exc:
        logger.warning(
            "turn_classification_unavailable; defaulting_to_answer_question "
            "error_type=%s",
            type(exc).__name__,
        )
        return _decision(intent="answer_question")


def _decision(
    *,
    intent: TurnIntent,
    flight_scope: FlightSearchScope | None = None,
    extension_days: int | None = None,
    changed_fields: list[ChangedTripField] | None = None,
    refresh_hotels: bool = False,
) -> TurnDecision:
    return TurnDecision(
        intent=intent,
        flight_scope=flight_scope,
        extension_days=extension_days,
        changed_fields=changed_fields or [],
        refresh_hotels=refresh_hotels,
    )


def _action_for_intent(intent: TurnIntent) -> str:
    if intent.startswith("suggest_") and intent.endswith("_flights"):
        return "flight_search"
    return {
        "suggest_hotels": "hotel_search",
        "extend_trip": "extend_trip",
        "answer_question": "answer_question",
        "unsupported": "unsupported",
    }.get(intent, "plan_trip")
