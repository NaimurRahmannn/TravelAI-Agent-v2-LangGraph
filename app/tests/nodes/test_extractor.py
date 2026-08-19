from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableLambda

from app.graph.nodes import extractor
from app.graph.nodes.extractor import (
    _apply_deterministic_fallback,
    _get_missing_required_fields,
    _merge_trip,
)
from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    ItineraryDay,
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
    assert _get_missing_required_fields(trip) == ["budget", "origin", "travelers"]


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
    assert _get_missing_required_fields(trip) == ["travelers"]


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
    assert _get_missing_required_fields(trip) == []


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
    assert _get_missing_required_fields(completed_trip) == []


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
    assert _get_missing_required_fields(trip) == []


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
    assert result["missing_fields"] == ["budget", "origin", "travelers"]
    assert result["needs_clarification"] is True
    assert result["itinerary"] is None


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
        },
        config={},
    )

    assert result["itinerary"] is None
    assert result["needs_clarification"] is True
