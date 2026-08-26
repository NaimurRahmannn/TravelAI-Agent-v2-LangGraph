from datetime import date, timedelta

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableLambda

from app.graph.nodes import extractor
from app.graph.nodes.extractor import (
    _apply_deterministic_fallback,
    _apply_selected_dates,
    _get_missing_required_fields,
    _merge_trip,
    _should_replace_preferences,
)
from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    ItineraryDay,
    Trip,
    TripExtraction,
    TripPlan,
)


def _empty_extraction() -> TripExtraction:
    return TripExtraction(
        origin=None,
        destination=None,
        start_date=None,
        end_date=None,
        duration=None,
        budget=None,
        currency=None,
        travelers=None,
        preferences=[],
    )


def test_thailand_request_recovers_destination_and_duration():
    """Obvious facts survive even when Groq returns an all-null extraction."""

    extraction = _apply_deterministic_fallback(
        _empty_extraction(),
        "Plan a Thailand trip for 5 days",
    )
    trip = _merge_trip(None, extraction)

    assert trip.destination == "Thailand"
    assert trip.duration == 5
    assert _get_missing_required_fields(trip) == [
        "budget",
        "dates",
        "origin",
        "travelers",
    ]


def test_preference_fallback_recovers_mountain_and_river_preferences():
    extraction = _apply_deterministic_fallback(
        _empty_extraction(),
        "I prefer top mountain places and rivers in Japan",
    )

    assert extraction.preferences == ["mountains", "rivers"]


def test_only_preference_replaces_existing_preferences():
    existing = Trip(
        destination="Japan",
        preferences=["temples", "food"],
    )
    follow_up = _apply_deterministic_fallback(
        _empty_extraction(),
        "I prefer only top mountain places in Japan",
    )

    trip = _merge_trip(
        existing,
        follow_up,
        replace_preferences=_should_replace_preferences(
            "I prefer only top mountain places in Japan"
        ),
    )

    assert trip.preferences == ["mountains"]


def test_fresh_preference_set_replaces_existing_preferences():
    existing = Trip(
        destination="Japan",
        preferences=["temples", "food"],
    )
    follow_up = _apply_deterministic_fallback(
        _empty_extraction(),
        "I prefer mountain and river places",
    )

    trip = _merge_trip(
        existing,
        follow_up,
        replace_preferences=_should_replace_preferences(
            "I prefer mountain and river places"
        ),
    )

    assert trip.preferences == ["mountains", "rivers"]


def test_additive_preference_wording_keeps_existing_preferences():
    existing = Trip(
        destination="Japan",
        preferences=["temples"],
    )
    follow_up = _apply_deterministic_fallback(
        _empty_extraction(),
        "Also add river places",
    )

    trip = _merge_trip(
        existing,
        follow_up,
        replace_preferences=_should_replace_preferences("Also add river places"),
    )

    assert trip.preferences == ["temples", "rivers"]


def test_preference_merge_normalizes_model_aliases_and_case():
    existing = Trip(destination="Japan", preferences=["Temples"])
    extracted = _empty_extraction().model_copy(
        update={"preferences": ["MOUNTAIN", "temple"]}
    )

    trip = _merge_trip(existing, extracted)

    assert trip.preferences == ["temples", "mountains"]


def test_japan_request_recovers_stated_fields_and_asks_for_travelers():
    """The reported Japan request should ask only for its unstated party size."""

    extraction = _apply_deterministic_fallback(
        _empty_extraction(),
        "I want to visit Japan from Bangladesh for 7 days with a budget of $2000",
    )
    trip = _merge_trip(None, extraction)

    assert trip.origin == "Bangladesh"
    assert trip.destination == "Japan"
    assert trip.duration == 7
    assert trip.budget == 2000
    assert trip.currency == "USD"
    assert _get_missing_required_fields(trip) == ["dates", "travelers"]


def test_follow_up_recovers_origin_budget_and_travelers():
    """A clarification reply can complete the remaining required fields."""

    existing = _merge_trip(
        None,
        _apply_deterministic_fallback(
            _empty_extraction(),
            "Plan a Thailand trip for 5 days",
        ),
    )
    follow_up = _apply_deterministic_fallback(
        _empty_extraction(),
        "From Bangladesh with a budget of $2000 for 2 travelers",
    )
    trip = _merge_trip(existing, follow_up)

    assert trip.origin == "Bangladesh"
    assert trip.travelers == 2
    assert trip.budget == 2000
    assert _get_missing_required_fields(trip) == ["dates"]


def test_short_unlabelled_clarification_reply_completes_trip_details():
    """Bare answers such as 'Bangladesh 2' should not repeat the same prompt."""

    initial_trip = _merge_trip(
        None,
        _apply_deterministic_fallback(
            _empty_extraction(),
            "Plan a Thailand trip for 5 days",
        ),
    )
    budget_and_origin = _apply_deterministic_fallback(
        _empty_extraction(),
        "$2000 dollar Bangladesh",
        missing_fields=_get_missing_required_fields(initial_trip),
        is_clarification_reply=True,
    )
    partial_trip = _merge_trip(initial_trip, budget_and_origin)
    final_reply = _apply_deterministic_fallback(
        _empty_extraction(),
        "Bangladesh 2",
        missing_fields=_get_missing_required_fields(partial_trip),
        is_clarification_reply=True,
    )
    completed_trip = _merge_trip(partial_trip, final_reply)

    assert partial_trip.origin == "Bangladesh"
    assert partial_trip.budget == 2000
    assert completed_trip.travelers == 2
    assert _get_missing_required_fields(completed_trip) == ["dates"]


def test_mixed_clarification_reply_recovers_unlabelled_origin():
    """Natural combined answers should not ask for the origin a second time."""

    initial_trip = _merge_trip(
        None,
        _apply_deterministic_fallback(
            _empty_extraction(),
            "Plan a Thailand trip for 5 days",
        ),
    )
    follow_up = _apply_deterministic_fallback(
        _empty_extraction(),
        "$2000 Bangladesh and 2 people",
        missing_fields=_get_missing_required_fields(initial_trip),
        is_clarification_reply=True,
    )
    trip = _merge_trip(initial_trip, follow_up)

    assert trip.origin == "Bangladesh"
    assert trip.travelers == 2
    assert trip.budget == 2000
    assert trip.currency == "USD"
    assert _get_missing_required_fields(trip) == ["dates"]


def test_picker_dates_are_stored_and_override_existing_duration():
    start_date = date.today() + timedelta(days=10)
    end_date = start_date + timedelta(days=4)
    trip = _apply_selected_dates(
        Trip(destination="Japan", duration=30),
        start_date,
        end_date,
    )

    assert trip.start_date == start_date
    assert trip.end_date == end_date
    assert trip.duration == 5


def test_date_update_preserves_other_trip_fields():
    original = Trip(
        origin="Dhaka",
        destination="Japan",
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=9),
        duration=5,
        budget=3000,
        budget_original=360000,
        currency="USD",
        travelers=2,
        preferences=["culture", "food"],
    )
    new_start = date.today() + timedelta(days=20)
    new_end = new_start + timedelta(days=6)

    updated = _apply_selected_dates(original, new_start, new_end)

    assert updated.start_date == new_start
    assert updated.end_date == new_end
    assert updated.duration == 7
    assert updated.origin == original.origin
    assert updated.destination == original.destination
    assert updated.travelers == original.travelers
    assert updated.budget == original.budget
    assert updated.budget_original == original.budget_original
    assert updated.currency == original.currency
    assert updated.preferences == original.preferences


def test_invalid_date_update_does_not_replace_existing_trip():
    old_start = date.today() + timedelta(days=10)
    old_end = old_start + timedelta(days=4)
    original = Trip(
        destination="Japan",
        start_date=old_start,
        end_date=old_end,
        duration=5,
    )

    with pytest.raises(ValueError, match="End date cannot be before start date"):
        _apply_selected_dates(
            original,
            old_start + timedelta(days=20),
            old_start + timedelta(days=19),
        )

    assert original.start_date == old_start
    assert original.end_date == old_end
    assert original.duration == 5


def test_same_day_picker_range_has_one_day_duration():
    travel_date = date.today() + timedelta(days=1)

    trip = _apply_selected_dates(Trip(destination="Japan"), travel_date, travel_date)

    assert trip.duration == 1


def test_llm_dates_are_not_authoritative_and_picker_dates_persist():
    selected_start = date.today() + timedelta(days=20)
    selected_end = selected_start + timedelta(days=2)
    trip = _apply_selected_dates(Trip(destination="Japan"), selected_start, selected_end)
    llm_follow_up = _empty_extraction().model_copy(
        update={
            "start_date": "2099-01-01",
            "end_date": "2099-01-20",
            "budget": 1000,
        }
    )

    merged = _merge_trip(trip, llm_follow_up)

    assert merged.start_date == selected_start
    assert merged.end_date == selected_end
    assert merged.duration == 3


def test_new_trip_without_checkpointed_state_starts_without_dates():
    trip = _merge_trip(
        None,
        _apply_deterministic_fallback(_empty_extraction(), "Plan a Japan trip"),
    )

    assert trip.start_date is None
    assert trip.end_date is None
    assert "dates" in _get_missing_required_fields(trip)


def test_non_trip_state_does_not_request_date_selection():
    assert _get_missing_required_fields(Trip()) == [
        "destination",
        "budget",
        "origin",
        "travelers",
    ]


def test_extraction_schema_requires_every_key_and_forbids_extra_fields():
    """Groq must not be allowed to satisfy the schema with an empty object."""

    schema = TripExtraction.model_json_schema()

    assert set(schema["required"]) == set(schema["properties"])
    assert schema["additionalProperties"] is False


def test_extractor_node_recovers_when_structured_model_returns_nulls(monkeypatch):
    """Exercise the complete extractor node against the reported failure mode."""

    class EmptyExtractionModel:
        def with_structured_output(self, schema, *, method, strict):
            assert schema is TripExtraction
            assert method == "json_schema"
            assert strict is True
            return RunnableLambda(lambda _: _empty_extraction())

    monkeypatch.setattr(
        extractor,
        "get_groq_llm",
        lambda: EmptyExtractionModel(),
    )

    result = extractor.extractor_node(
        {
            "messages": [
                HumanMessage(content="Plan a Thailand trip for 5 days"),
            ],
        },
        config={},
    )

    assert result["trip"].destination == "Thailand"
    assert result["trip"].duration == 5
    assert result["missing_fields"] == ["budget", "dates", "origin", "travelers"]
    assert result["needs_clarification"] is True
    assert result["itinerary"] is None
    assert result["travel_selections"] is None
    assert result["trip_cost_summary"] is None
    assert result["detailed_routing_plan"] is None


def test_missing_detail_reply_cannot_replace_confirmed_destination(monkeypatch):
    """A country supplied as origin must not overwrite the planned destination."""

    model_output = _empty_extraction().model_copy(
        update={
            "destination": "Bangladesh",
            "duration": 2,
            "budget": 2000,
            "currency": "USD",
            "travelers": 2,
        }
    )

    class MisclassifiedExtractionModel:
        def with_structured_output(self, schema, *, method, strict):
            return RunnableLambda(lambda _: model_output)

    monkeypatch.setattr(
        extractor,
        "get_groq_llm",
        lambda: MisclassifiedExtractionModel(),
    )
    existing_trip = Trip(
        destination="Nepal",
        start_date=date(2026, 8, 20),
        end_date=date(2026, 8, 23),
        duration=4,
    )

    result = extractor.extractor_node(
        {
            "messages": [HumanMessage(content="$2000 Bangladesh 2")],
            "trip": existing_trip,
        },
        config={},
    )

    assert result["trip"].destination == "Nepal"
    assert result["trip"].origin == "Bangladesh"
    assert result["trip"].duration == 4
    assert result["trip"].start_date == date(2026, 8, 20)
    assert result["trip"].end_date == date(2026, 8, 23)
    assert result["trip"].budget == 2000
    assert result["trip"].travelers == 2
    assert result["missing_fields"] == []
    assert result["needs_clarification"] is False


def test_structured_provider_failure_uses_deterministic_extraction(monkeypatch):
    """Groq JSON validation errors must clarify rather than terminate the turn."""

    def fail(_):
        raise RuntimeError("json_validate_failed")

    class FailingExtractionModel:
        def with_structured_output(self, schema, *, method, strict):
            return RunnableLambda(fail)

    monkeypatch.setattr(
        extractor,
        "get_groq_llm",
        lambda: FailingExtractionModel(),
    )

    result = extractor.extractor_node(
        {
            "messages": [HumanMessage(content="Plan a Nepal trip for 5 days")],
        },
        config={},
    )

    assert result["trip"].destination == "Nepal"
    assert result["trip"].duration == 5
    assert result["missing_fields"] == [
        "budget",
        "dates",
        "origin",
        "travelers",
    ]
    assert result["needs_clarification"] is True


def test_provider_failure_during_destination_change_clears_stale_dates(monkeypatch):
    def fail(_):
        raise RuntimeError("json_validate_failed")

    class FailingExtractionModel:
        def with_structured_output(self, schema, *, method, strict):
            return RunnableLambda(fail)

    monkeypatch.setattr(
        extractor,
        "get_groq_llm",
        lambda: FailingExtractionModel(),
    )
    existing_trip = Trip(
        origin="Bangladesh",
        destination="Japan",
        start_date=date(2026, 8, 20),
        end_date=date(2026, 8, 22),
        duration=3,
        budget=2000,
        currency="USD",
        travelers=2,
    )

    result = extractor.extractor_node(
        {
            "messages": [HumanMessage(content="Plan a Nepal trip for 5 days")],
            "trip": existing_trip,
        },
        config={},
    )

    assert result["trip"].destination == "Nepal"
    assert result["trip"].duration == 5
    assert result["trip"].start_date is None
    assert result["trip"].end_date is None
    assert result["trip"].origin == "Bangladesh"
    assert result["trip"].budget == 2000
    assert result["trip"].travelers == 2
    assert result["missing_fields"] == ["dates"]
    assert result["needs_clarification"] is True


def test_explicit_new_destination_clears_previous_trip_dates():
    existing_trip = Trip(
        origin="Bangladesh",
        destination="Japan",
        start_date=date(2026, 8, 20),
        end_date=date(2026, 8, 22),
        duration=3,
        budget=2000,
        currency="USD",
        travelers=2,
    )
    extracted_trip = _empty_extraction().model_copy(
        update={"destination": "Nepal", "duration": 5}
    )

    merged = _merge_trip(existing_trip, extracted_trip)

    assert merged.destination == "Nepal"
    assert merged.duration == 5
    assert merged.start_date is None
    assert merged.end_date is None
    assert merged.origin == "Bangladesh"
    assert merged.budget == 2000
    assert merged.travelers == 2


def test_extractor_clears_checkpointed_itinerary_on_new_turn(monkeypatch):
    """A prior plan cannot leak into a later clarification or rejection turn."""

    class EmptyExtractionModel:
        def with_structured_output(self, schema, *, method, strict):
            return RunnableLambda(lambda _: _empty_extraction())

    stale_plan = TripPlan(
        title="Old plan",
        origin="Dhaka",
        destination="Japan",
        duration_days=1,
        travelers=1,
        summary=None,
        preferences=[],
        days=[
            ItineraryDay(
                day_number=1,
                city="Tokyo",
                activities=[Activity(name="Old activity", category="visit")],
            )
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Trip", amount_usd=100)],
            estimated_total_usd=100,
            user_budget_usd=100,
        ),
        practical_notes=[],
    )
    monkeypatch.setattr(extractor, "get_groq_llm", lambda: EmptyExtractionModel())

    result = extractor.extractor_node(
        {
            "messages": [HumanMessage(content="Plan another trip")],
            "itinerary": stale_plan,
            "travel_selections": {"selected_flight_id": "old"},
            "trip_cost_summary": {"updated_trip_total_usd": 9999},
            "detailed_routing_plan": {"days": ["stale"]},
        },
        config={},
    )

    assert result["itinerary"] is None
    assert result["travel_selections"] is None
    assert result["trip_cost_summary"] is None
    assert result["detailed_routing_plan"] is None
    assert result["needs_clarification"] is True


def test_extractor_marks_changed_preferences_and_clears_selection(monkeypatch):
    class EmptyExtractionModel:
        def with_structured_output(self, schema, *, method, strict):
            return RunnableLambda(lambda _: _empty_extraction())

    monkeypatch.setattr(extractor, "get_groq_llm", lambda: EmptyExtractionModel())
    existing_trip = Trip(
        origin="Dhaka",
        destination="Japan",
        start_date=date(2026, 9, 10),
        end_date=date(2026, 9, 12),
        duration=3,
        budget=2000,
        currency="USD",
        travelers=2,
        preferences=["mountains"],
    )

    result = extractor.extractor_node(
        {
            "messages": [HumanMessage(content="Also add temples")],
            "trip": existing_trip,
            "travel_selections": {"selected_flight_id": "old-selection"},
        },
        config={},
    )

    assert result["trip"].preferences == ["mountains", "temples"]
    assert result["preferences_changed"] is True
    assert result["travel_selections"] is None
