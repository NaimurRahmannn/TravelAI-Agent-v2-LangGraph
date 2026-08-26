import re
from datetime import date as CalendarDate, timedelta
from time import perf_counter

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, ConfigDict, Field

from app.core.logging import get_logger
from app.graph.prompts.itinerary import itinerary_prompt
from app.graph.state import TravelState
from app.llm import get_gemini_llm
from app.models import BudgetBreakdown, PreferenceTag, TravelMode, Trip, TripPlan
from app.models.itinerary import _is_flight_ticket_activity
from app.models.preferences import preference_tag_for
from app.services.message_content import message_content_to_text
from app.services.trip_dates import validate_and_derive_duration

logger = get_logger(__name__)


class ItineraryGenerationActivity(BaseModel):
    """Activity fields the LLM owns before trusted provider enrichment."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    place_search_name: str | None = Field(default=None, min_length=1)
    category: str = Field(min_length=1)
    location_hint: str | None = None
    description: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    reason_for_recommendation: str | None = None
    preference_tags: list[PreferenceTag]
    travel_mode_to_next: TravelMode | None = None


class ItineraryGenerationDay(BaseModel):
    """Day fields the LLM owns before date, weather, and route enrichment."""

    model_config = ConfigDict(extra="forbid")

    day_number: int = Field(ge=1)
    city: str = Field(min_length=1)
    activities: list[ItineraryGenerationActivity] = Field(
        min_length=1,
        max_length=3,
    )
    estimated_daily_cost_usd: float | None = Field(default=None, ge=0)


class ItineraryGenerationOutput(BaseModel):
    """LLM-owned planning fields, excluding trusted provider data."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    origin: str | None = None
    destination: str = Field(min_length=1)
    start_date: CalendarDate | None = None
    end_date: CalendarDate | None = None
    duration_days: int = Field(ge=1)
    travelers: int = Field(ge=1)
    summary: str | None = None
    preferences: list[str]
    days: list[ItineraryGenerationDay] = Field(min_length=1)
    budget: BudgetBreakdown
    practical_notes: list[str]


class PreferenceValidationError(ValueError):
    """Generated discretionary activities do not match active preferences."""


def itinerary_generator_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, TripPlan | None]:
    """Generate the authoritative structured itinerary with graceful fallback."""

    started_at = perf_counter()
    trip = state.get("trip")
    logger.info(
        "itinerary_generator_node entered destination=%s duration=%s",
        trip.destination if trip else None,
        trip.duration if trip else None,
    )

    try:
        complete_trip = _require_complete_trip(trip)
        structured_llm = get_gemini_llm().with_structured_output(
            ItineraryGenerationOutput,
            method="json_schema",
        )
        chain = itinerary_prompt | structured_llm
        context = _build_generation_context(state, complete_trip)
        plan = None
        for attempt in range(2):
            raw_plan = chain.invoke(context, config=config)
            candidate = _coerce_trip_plan(raw_plan)
            candidate = _clear_untrusted_place_enrichment(candidate)
            candidate = _apply_authoritative_trip(candidate, complete_trip)
            candidate = _normalize_plan_details(candidate)
            _validate_day_structure(candidate)
            try:
                _validate_preference_alignment(candidate)
            except PreferenceValidationError as exc:
                if attempt == 1:
                    raise
                logger.info("itinerary_preference_retry attempt=%s", attempt + 2)
                context["validation_feedback"] = str(exc)
                continue
            plan = candidate
            break
    except Exception:
        logger.exception(
            "structured itinerary generation failed; using agent text fallback"
        )
        plan = None

    duration = perf_counter() - started_at
    logger.info(
        "itinerary_generator_node exited generated=%s duration=%.4fs",
        plan is not None,
        duration,
    )
    return {"itinerary": plan}


def _build_generation_context(state: TravelState, trip: Trip) -> dict[str, str]:
    """Collect the focused planning context supplied to structured Gemini."""

    research_summary = state.get("research_results", {}).get("summary", "")
    memories = state.get("long_term_memories", [])
    return {
        "trip": trip.model_dump_json(),
        "latest_user_request": _latest_message_text(state["messages"], HumanMessage),
        "memories": "\n".join(f"- {memory}" for memory in memories) or "None",
        "research_summary": research_summary or "None",
        "validation_feedback": "None; this is the first generation attempt.",
    }


def _latest_message_text(
    messages: list[BaseMessage],
    message_type: type[BaseMessage],
) -> str:
    """Return clean text from the latest message of the requested type."""

    for message in reversed(messages):
        if isinstance(message, message_type):
            return message_content_to_text(message.content)
    return ""


def _require_complete_trip(trip: Trip | None) -> Trip:
    """Return complete authoritative trip context or fail into text fallback."""

    if (
        trip is None
        or not trip.destination
        or trip.start_date is None
        or trip.end_date is None
        or trip.travelers is None
        or trip.travelers < 1
    ):
        raise ValueError("Structured itinerary requires complete trip context")
    duration = validate_and_derive_duration(trip.start_date, trip.end_date)
    return trip.model_copy(update={"duration": duration})


def _coerce_trip_plan(raw_plan: object) -> TripPlan:
    """Validate structured-model output regardless of returned representation."""

    if isinstance(raw_plan, TripPlan):
        return raw_plan
    if isinstance(raw_plan, ItineraryGenerationOutput):
        return TripPlan.model_validate(raw_plan.model_dump())
    return TripPlan.model_validate(raw_plan)


def _clear_untrusted_place_enrichment(plan: TripPlan) -> TripPlan:
    """Remove provider metadata that may have been invented by the LLM."""

    plan_data = plan.model_dump()
    plan_data["recommendations"] = None
    for day in plan_data["days"]:
        day["weather"] = None
        day["weather_status"] = "skipped"
        day["travel_legs"] = []
        for activity in day["activities"]:
            activity["place"] = None
            activity["place_resolution_status"] = "unresolved"
            activity["image"] = None
    return TripPlan.model_validate(plan_data)


def _apply_authoritative_trip(plan: TripPlan, trip: Trip) -> TripPlan:
    """Replace LLM-owned copies of known trip fields with extracted state values."""

    plan_data = plan.model_dump()
    plan_data.update(
        {
            "origin": trip.origin,
            "destination": trip.destination,
            "start_date": trip.start_date,
            "end_date": trip.end_date,
            "duration_days": trip.duration,
            "travelers": trip.travelers,
            "guest_nationality_country_code": None,
            "preferences": trip.preferences,
        }
    )
    for day in plan_data["days"]:
        day["date"] = trip.start_date + timedelta(days=day["day_number"] - 1)
    plan_data["budget"]["user_budget_usd"] = trip.budget
    return TripPlan.model_validate(plan_data)


def _validate_day_structure(plan: TripPlan) -> None:
    """Enforce only the core duration and sequential-numbering invariants."""

    if len(plan.days) != plan.duration_days:
        raise ValueError("Itinerary day count does not match trip duration")

    expected_numbers = list(range(1, plan.duration_days + 1))
    actual_numbers = [day.day_number for day in plan.days]
    if actual_numbers != expected_numbers:
        raise ValueError("Itinerary days must be sequential")


def _validate_preference_alignment(plan: TripPlan) -> None:
    """Require each discretionary activity to match the active known interests."""

    active_tags = {
        tag
        for preference in plan.preferences
        if (tag := preference_tag_for(preference)) is not None
    }
    if not active_tags:
        return

    violations: list[str] = []
    matching_activity_count = 0
    for day in plan.days:
        for activity in day.activities:
            if _is_required_schedule_activity(activity, active_tags):
                continue
            activity_tags = set(activity.preference_tags)
            if not activity_tags or not activity_tags <= active_tags:
                rendered_tags = ", ".join(
                    sorted(tag.value for tag in activity_tags)
                ) or "none"
                violations.append(
                    f"Day {day.day_number} '{activity.name}' has tags "
                    f"[{rendered_tags}]"
                )
            else:
                matching_activity_count += 1

    if matching_activity_count == 0 and not violations:
        violations.append("the itinerary has no preference-focused activity")

    if violations:
        allowed = ", ".join(sorted(tag.value for tag in active_tags))
        details = "; ".join(violations)
        raise PreferenceValidationError(
            "Regenerate the complete itinerary. Every discretionary activity "
            f"must use only these active preference tags: [{allowed}]. "
            f"Violations: {details}. Required transfers, lodging, rest, and "
            "non-preference meals may use an empty preference_tags list."
        )


def _is_required_schedule_activity(
    activity: object,
    active_tags: set[PreferenceTag],
) -> bool:
    """Return whether an activity is necessary trip pacing rather than an interest."""

    name = str(getattr(activity, "name", "")).casefold()
    category = str(getattr(activity, "category", "")).casefold()
    normalized = f"{name} {category}"
    logistics_terms = (
        "airport",
        "arrival",
        "departure",
        "flight",
        "hotel check",
        "check-in",
        "check in",
        "check-out",
        "check out",
        "lodging",
        "accommodation",
        "transfer",
        "transport",
        "transit",
        "train to",
        "bus to",
    )
    if any(term in normalized for term in logistics_terms):
        return True
    if any(term in normalized for term in ("rest", "free time", "break")):
        return True

    meal_terms = ("meal", "breakfast", "lunch", "dinner", "restaurant", "cafe")
    is_meal = any(term in normalized for term in meal_terms) or category == "food"
    return is_meal and PreferenceTag.FOOD not in active_tags


def _normalize_plan_details(plan: TripPlan) -> TripPlan:
    """Normalize planning hints, budget scope, notes, and listed activity costs."""

    plan_data = plan.model_dump()
    _fill_location_hints(plan_data)
    _normalize_base_trip_budget_note(plan_data)
    _normalize_visa_guidance(plan_data)
    _reconcile_activity_budget_categories(plan_data)
    _ensure_contingency_reserve(plan_data)
    _normalize_contingency_guidance(plan_data)
    _add_cross_city_logistics_notes(plan_data)
    normalized = TripPlan.model_validate(plan_data)
    return _calculate_listed_activity_costs(normalized)


def _fill_location_hints(plan_data: dict) -> None:
    """Provide deterministic planning hints without external place metadata."""

    destination = plan_data["destination"]
    for day in plan_data["days"]:
        for activity in day["activities"]:
            if not activity.get("location_hint"):
                activity["location_hint"] = (
                    f"{activity['name']}, {day['city']}, {destination}"
                )


def _normalize_base_trip_budget_note(plan_data: dict) -> None:
    """Keep traveler-facing notes aligned with the model-level budget scope."""

    plan_data["practical_notes"][:] = [
        item
        for item in plan_data["practical_notes"]
        if not _is_obsolete_cost_scope_note(item)
    ]
    note = (
        "Flights and accommodation are not included in the base trip estimate; "
        "review them separately before booking."
    )
    if not any(
        "flights and accommodation" in item.casefold()
        for item in plan_data["practical_notes"]
    ):
        plan_data["practical_notes"].append(note)


def _is_obsolete_cost_scope_note(note: str) -> bool:
    """Remove generated budget-scope claims superseded by the base estimate."""

    normalized = note.casefold()
    mentions_excluded_cost = any(
        term in normalized
        for term in ("flight", "airfare", "accommodation", "lodging", "hotel room")
    )
    mentions_estimate = "budget" in normalized or "estimate" in normalized
    mentions_scope = "included" in normalized or "excluded" in normalized
    return mentions_excluded_cost and mentions_estimate and mentions_scope


def _normalize_visa_guidance(plan_data: dict) -> None:
    """Replace potentially inferred or unverified visa claims with safe guidance."""

    notes = plan_data["practical_notes"]
    safe_note = (
        f"Visa: Verify current entry requirements for your actual passport with "
        f"the official embassy or immigration authority for {plan_data['destination']} "
        "before booking; departure location does not determine nationality."
    )
    visa_indexes = [
        index
        for index, note in enumerate(notes)
        if "visa" in note.casefold() or "entry requirement" in note.casefold()
    ]
    if visa_indexes:
        notes[visa_indexes[0]] = safe_note
        for index in reversed(visa_indexes[1:]):
            notes.pop(index)


def _ensure_contingency_reserve(plan_data: dict) -> None:
    """Reserve part of a sufficient user budget for unplanned costs."""

    budget = plan_data["budget"]
    user_budget = budget.get("user_budget_usd")
    items = budget["items"]
    if user_budget is None or user_budget <= 0:
        return

    reserve_items = [item for item in items if _is_contingency_category(item["category"])]
    planned_items = [item for item in items if not _is_contingency_category(item["category"])]
    planned_total = sum(item["amount_usd"] for item in planned_items)
    if planned_total > user_budget:
        items[:] = planned_items
        return

    if reserve_items:
        reserve_total = sum(item["amount_usd"] for item in reserve_items)
        if planned_total + reserve_total > user_budget:
            items[:] = planned_items
        return

    reserve = round(user_budget * 0.05, 2)
    available_for_planned_costs = round(user_budget - reserve, 2)
    if planned_total > available_for_planned_costs:
        return

    items.append(
        {
            "category": "Contingency reserve",
            "amount_usd": reserve,
            "note": "Reserved for unexpected costs rather than planned spending.",
        }
    )


def _is_contingency_category(category: str) -> bool:
    """Return whether a budget category represents unplanned-cost reserves."""

    reserve_terms = ("contingency", "emergency", "reserve")
    return any(term in category.casefold() for term in reserve_terms)


def _normalize_contingency_guidance(plan_data: dict) -> None:
    """Keep practical contingency claims consistent with actual budget items."""

    has_reserve = any(
        _is_contingency_category(item["category"])
        for item in plan_data["budget"]["items"]
    )
    notes = plan_data["practical_notes"]
    contingency_terms = ("contingency", "emergency reserve", "incidental buffer")
    if not has_reserve:
        notes[:] = [
            note
            for note in notes
            if not any(term in note.casefold() for term in contingency_terms)
        ]


def _reconcile_activity_budget_categories(plan_data: dict) -> None:
    """Ensure budget categories cover every explicitly priced activity."""

    listed_costs: dict[str, float] = {}
    for day in plan_data["days"]:
        for activity in day["activities"]:
            cost = activity.get("estimated_cost_usd")
            if cost is None:
                continue
            if _is_flight_ticket_activity(
                activity.get("name", ""),
                activity.get("category"),
            ):
                continue
            category = _activity_budget_category(activity)
            listed_costs[category] = listed_costs.get(category, 0.0) + cost

    budget_items = plan_data["budget"]["items"]
    for category, listed_total in listed_costs.items():
        matching_items = [
            item
            for item in budget_items
            if _budget_item_category(item["category"]) == category
        ]
        covered_total = sum(item["amount_usd"] for item in matching_items)
        if covered_total >= listed_total:
            continue

        difference = round(listed_total - covered_total, 2)
        note = (
            f"Includes at least ${listed_total:,.2f} of explicitly listed "
            "activity costs."
        )
        if matching_items:
            matching_items[0]["amount_usd"] = round(
                matching_items[0]["amount_usd"] + difference,
                2,
            )
            existing_note = matching_items[0].get("note")
            matching_items[0]["note"] = (
                f"{existing_note.rstrip('.')} — {note}"
                if existing_note
                else note
            )
        else:
            budget_items.append(
                {
                    "category": category,
                    "amount_usd": round(listed_total, 2),
                    "note": note,
                }
            )


def _activity_budget_category(activity: dict) -> str:
    """Map a planned activity into a stable display budget category."""

    text = f"{activity.get('category', '')} {activity.get('name', '')}".casefold()
    if any(term in text for term in ("food", "dining", "dinner", "lunch", "brunch", "restaurant")):
        return "Food and Dining"
    if any(term in text for term in ("shopping", "souvenir", "retail")):
        return "Shopping and Miscellaneous"
    if any(term in text for term in ("transfer", "transport", "taxi", "train", "bus", "car")):
        return "Local Transportation"
    return "Activities and Tours"


def _budget_item_category(category: str) -> str:
    """Normalize free-form budget labels to stable reconciliation categories."""

    text = category.casefold()
    if any(
        term in text
        for term in ("food", "dining", "meal", "drink", "restaurant")
    ):
        return "Food and Dining"
    if any(term in text for term in ("shopping", "souvenir", "miscellaneous")):
        return "Shopping and Miscellaneous"
    if any(term in text for term in ("transfer", "transport", "taxi", "train", "bus", "car")):
        return "Local Transportation"
    if _is_contingency_category(category):
        return "Contingency reserve"
    return "Activities and Tours"


def _add_cross_city_logistics_notes(plan_data: dict) -> None:
    """Audit cross-city days for an explicitly priced round-trip transfer."""

    notes = plan_data["practical_notes"]
    for day in plan_data["days"]:
        outside_activities = [
            activity["name"]
            for activity in day["activities"]
            if day["city"].casefold()
            not in (activity.get("location_hint") or "").casefold()
        ]
        if not outside_activities:
            continue
        if _has_priced_round_trip_transfer(day):
            continue
        activity_names = ", ".join(outside_activities)
        note = (
            f"Day {day['day_number']} includes stops outside {day['city']} "
            f"({activity_names}) without an explicitly priced round-trip transfer. "
            "The missing outbound/return transportation is not included in the "
            "estimate; confirm travel time and add its cost before booking."
        )
        if note not in notes:
            notes.append(note)


def _has_priced_round_trip_transfer(day: dict) -> bool:
    """Return whether a day includes priced transport in both directions."""

    round_trip_terms = ("round-trip", "round trip", "return transfer", "both ways")
    for activity in day["activities"]:
        text = (
            f"{activity.get('name', '')} {activity.get('category', '')} "
            f"{activity.get('description', '')}"
        ).casefold()
        if (
            any(term in text for term in round_trip_terms)
            and activity.get("estimated_cost_usd") is not None
        ):
            return True
    return False


def _calculate_listed_activity_costs(plan: TripPlan) -> TripPlan:
    """Calculate each day only from activities with explicit cost estimates."""

    plan_data = plan.model_dump()
    for day in plan_data["days"]:
        listed_costs = [
            activity["estimated_cost_usd"]
            for activity in day["activities"]
            if activity.get("estimated_cost_usd") is not None
        ]
        day["estimated_daily_cost_usd"] = (
            round(sum(listed_costs), 2)
            if listed_costs
            else None
        )
    return TripPlan.model_validate(plan_data)
