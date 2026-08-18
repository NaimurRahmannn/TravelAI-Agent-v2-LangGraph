from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableLambda

from app.graph.nodes import extractor
from app.graph.nodes.extractor import (
    _apply_deterministic_fallback,
    _get_missing_required_fields,
    _merge_trip,
)
from app.models import TripExtraction


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
    assert _get_missing_required_fields(trip) == ["budget"]


def test_complete_japan_request_recovers_all_required_fields():
    """The reported Japan request should not route to clarification."""

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
    assert result["missing_fields"] == ["budget"]
    assert result["needs_clarification"] is True
