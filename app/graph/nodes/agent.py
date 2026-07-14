from time import perf_counter

from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig

from app.core.logging import get_logger
from app.graph.state import TravelState
from app.llm import get_tool_enabled_llm

logger = get_logger(__name__)


def agent_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, list[AIMessage] | bool | dict[str, Any] | None]:
    """Reason over the conversation and decide whether tools are needed."""

    started_at = perf_counter()
    has_research = bool(state.get("research_results", {}).get("summary"))
    logger.info(
        "MainGraph.Agent entered tool_count=%s tool_names=%s has_research=%s",
        0,
        [],
        has_research,
    )

    llm = get_tool_enabled_llm()
    messages = _build_agent_messages(state)
    response = llm.invoke(
        messages,
        config=config,
    )

    tool_names = [
        tool_call["name"]
        for tool_call in response.tool_calls
    ]
    approval_context = _build_approval_context(response)
    approval_required = approval_context is not None
    duration = perf_counter() - started_at
    logger.info(
        "MainGraph.Agent exited tool_count=%s tool_names=%s has_research=%s approval_required=%s duration=%.4fs",
        len(tool_names),
        tool_names,
        has_research,
        approval_required,
        duration,
    )

    return {
        "messages": [
            response,
        ],
        "approval_required": approval_required,
        "approval_context": approval_context,
        "approved": None,
    }


def _build_agent_messages(state: TravelState) -> list[BaseMessage]:
    """Return message history enriched with merged research context."""

    messages = _build_relevant_history(state["messages"])
    context_messages = [_build_trip_context_message(state)]
    research_summary = state.get("research_results", {}).get("summary")

    if research_summary:
        context_messages.append(
            SystemMessage(
                content=(
                    "Use this destination research when helpful. Do not mention "
                    "that it came from an internal research subgraph.\n\n"
                    f"{research_summary}"
                )
            )
        )

    return [
        *context_messages,
        *messages,
    ]


def _build_trip_context_message(state: TravelState) -> SystemMessage:
    """Build current trip context and follow-up instructions for the agent."""

    trip = state.get("trip")
    latest_user_message = _get_latest_user_message(state["messages"])
    latest_preferences = _extract_latest_preferences(latest_user_message)
    trip_details = trip.model_dump_json() if trip is not None else "None"
    preference_instruction = _build_preference_instruction(latest_preferences)

    return SystemMessage(
        content=(
            "You are continuing a travel planning conversation. Use the current "
            "trip state and pay special attention to the latest user message. "
            "If the latest user message adds preferences, constraints, or changes, "
            "the response must directly incorporate them and avoid repeating the "
            "previous answer unchanged. For preferences like temples, food, and "
            "nature, give concrete recommendations or itinerary adjustments for "
            "those interests.\n\n"
            f"{preference_instruction}"
            f"Current trip state:\n{trip_details}\n\n"
            f"Latest user message:\n{latest_user_message}"
        )
    )


def _get_latest_user_message(messages: list[BaseMessage]) -> str:
    """Return the latest human message content from the message history."""

    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return str(message.content)

    return ""


def _extract_latest_preferences(latest_user_message: str) -> list[str]:
    """Extract common travel preferences from the latest user message."""

    preference_terms = [
        "temples",
        "temple",
        "food",
        "cuisine",
        "nature",
        "gardens",
        "garden",
        "parks",
        "park",
        "hiking",
        "museums",
        "museum",
        "shopping",
        "nightlife",
        "beaches",
        "beach",
        "history",
        "culture",
    ]
    lowered_message = latest_user_message.lower()
    preferences: list[str] = []

    for term in preference_terms:
        if term in lowered_message:
            normalized_term = _normalize_preference(term)
            if normalized_term not in preferences:
                preferences.append(normalized_term)

    return preferences


def _normalize_preference(preference: str) -> str:
    """Normalize preference words for agent instructions."""

    preference_map = {
        "temple": "temples",
        "cuisine": "food",
        "garden": "nature",
        "gardens": "nature",
        "park": "nature",
        "parks": "nature",
        "hiking": "nature",
        "museum": "museums",
        "beach": "beaches",
        "culture": "culture",
    }
    return preference_map.get(preference, preference)


def _build_preference_instruction(preferences: list[str]) -> str:
    """Build a strict response instruction for latest-turn preferences."""

    if not preferences:
        return ""

    return (
        "The latest user message explicitly adds these preferences: "
        f"{', '.join(preferences)}. The final response must include concrete, "
        "named suggestions or itinerary adjustments for each of these preference "
        "areas, using the preference words directly as labels where natural.\n\n"
    )


def _build_relevant_history(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Keep user history and the active tool exchange, dropping stale final answers."""

    relevant_messages: list[BaseMessage] = [
        message
        for message in messages
        if isinstance(message, HumanMessage)
    ]

    active_tool_messages = _get_active_tool_exchange(messages)
    relevant_messages.extend(active_tool_messages)

    return relevant_messages


def _get_active_tool_exchange(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Return the latest AI tool-call message and its ToolMessages, if present."""

    last_tool_message_index = -1
    for index, message in enumerate(messages):
        if isinstance(message, ToolMessage):
            last_tool_message_index = index

    if last_tool_message_index == -1:
        return []

    tool_call_index = -1
    for index in range(last_tool_message_index, -1, -1):
        message = messages[index]
        if isinstance(message, AIMessage) and message.tool_calls:
            tool_call_index = index
            break

    if tool_call_index == -1:
        return []

    return list(messages[tool_call_index : last_tool_message_index + 1])


def _build_approval_context(message: AIMessage) -> dict[str, Any] | None:
    """Return approval context for sensitive tool calls, if present."""

    sensitive_calls = [
        tool_call
        for tool_call in message.tool_calls
        if _requires_approval(tool_call["name"])
    ]

    if not sensitive_calls:
        return None

    action_names = [
        tool_call["name"]
        for tool_call in sensitive_calls
    ]
    return {
        "action": _classify_action(action_names),
        "summary": f"Approval is required before executing: {', '.join(action_names)}.",
        "tool_calls": sensitive_calls,
        "supported_workflows": [
            "hotel_booking",
            "flight_booking",
            "trip_cancellation",
            "payment",
        ],
    }


def _requires_approval(tool_name: str) -> bool:
    """Return whether a tool name represents a sensitive action."""

    lowered_name = tool_name.lower()
    sensitive_terms = [
        "book",
        "booking",
        "hotel",
        "flight",
        "cancel",
        "cancellation",
        "payment",
        "pay",
        "purchase",
        "charge",
    ]
    return any(term in lowered_name for term in sensitive_terms)


def _classify_action(tool_names: list[str]) -> str:
    """Classify sensitive tool calls into an approval workflow action."""

    joined_names = " ".join(tool_names).lower()

    if "hotel" in joined_names:
        return "hotel_booking"

    if "flight" in joined_names:
        return "flight_booking"

    if "cancel" in joined_names or "cancellation" in joined_names:
        return "trip_cancellation"

    if "payment" in joined_names or "pay" in joined_names or "charge" in joined_names:
        return "payment"

    return "sensitive_tool_execution"
