import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import TypedDict

import aiosqlite
import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from app.models import (
    FlightOption,
    FlightSearchCache,
    FlightSearchRequest,
    FlightSegment,
    FlightSlice,
    RecommendationDomainState,
)
from app.services.flight_recommendation import (
    FLIGHT_SEARCH_CACHE_TTL_SECONDS,
    can_reuse_flight_cache,
    flight_requests_match,
    is_flight_cache_fresh,
)

NOW = datetime(2026, 8, 22, 10, tzinfo=UTC)


def _request(**updates) -> FlightSearchRequest:
    values = {
        "origin": "Dhaka",
        "destination": "Tokyo",
        "return_origin": "Osaka",
        "return_destination": "Dhaka",
        "origin_country_hint": "BD",
        "destination_country_hint": "JP",
        "return_origin_country_hint": "JP",
        "return_destination_country_hint": "BD",
        "departure_date": date(2026, 9, 10),
        "return_date": date(2026, 9, 15),
        "adults": 2,
    }
    values.update(updates)
    return FlightSearchRequest(**values)


def _flight() -> FlightOption:
    departure = datetime(2026, 9, 10, 2, tzinfo=UTC)
    arrival = departure + timedelta(hours=7)
    segment = FlightSegment(
        origin_code="DAC",
        destination_code="HND",
        departure_at=departure,
        arrival_at=arrival,
        duration_minutes=420,
        airline_name="Example Airways",
    )
    return FlightOption(
        provider="swoop",
        provider_offer_id="flight_abc",
        origin_code="DAC",
        destination_code="HND",
        adults=2,
        total_duration_minutes=420,
        stops=0,
        total_price=714.20,
        currency="USD",
        price_type="shopping_total",
        airline_names=["Example Airways"],
        slices=[
            FlightSlice(
                origin_code="DAC",
                destination_code="HND",
                departure_at=departure,
                arrival_at=arrival,
                duration_minutes=420,
                stops=0,
                segments=[segment],
            )
        ],
        fetched_at=NOW,
    )


def _cache(
    *,
    request: FlightSearchRequest | None = None,
    status: str = "available",
    searched_at: datetime = NOW,
) -> FlightSearchCache:
    available = status == "available"
    return FlightSearchCache(
        request=request or _request(),
        flights=[_flight()] if available else [],
        status=RecommendationDomainState(
            status=status,
            provider_result_count=1 if available else 0,
        ),
        searched_at=searched_at,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("origin", "Chittagong"),
        ("destination", "Osaka"),
        ("return_origin", "Hiroshima"),
        ("return_destination", "Chittagong"),
        ("origin_country_hint", "IN"),
        ("destination_country_hint", "KR"),
        ("return_origin_country_hint", "KR"),
        ("return_destination_country_hint", "IN"),
        ("departure_date", date(2026, 9, 12)),
        ("return_date", date(2026, 9, 18)),
        ("adults", 3),
    ],
)
def test_complete_normalized_request_is_the_cache_identity(field, value):
    original = _request()
    changed = original.model_copy(update={field: value})

    assert flight_requests_match(original, original.model_copy()) is True
    assert flight_requests_match(original, changed) is False
    assert can_reuse_flight_cache(_cache(), changed, NOW) is False


def test_cache_ttl_is_fifteen_minutes_and_boundaries_are_deterministic():
    assert FLIGHT_SEARCH_CACHE_TTL_SECONDS == 15 * 60
    assert is_flight_cache_fresh(_cache(searched_at=NOW), NOW) is True
    assert (
        is_flight_cache_fresh(
            _cache(searched_at=NOW - timedelta(seconds=899)),
            NOW,
        )
        is True
    )
    assert (
        is_flight_cache_fresh(
            _cache(searched_at=NOW - timedelta(seconds=901)),
            NOW,
        )
        is False
    )


def test_no_results_is_reusable_but_unavailable_is_not():
    assert can_reuse_flight_cache(_cache(status="no_results"), _request(), NOW)
    assert not can_reuse_flight_cache(_cache(status="unavailable"), _request(), NOW)


def test_cache_requires_timezone_aware_searched_at_and_normalizes_to_utc():
    with pytest.raises(ValidationError, match="timezone-aware"):
        _cache(searched_at=datetime(2026, 8, 22, 10))

    offset_cache = _cache(
        searched_at=datetime.fromisoformat("2026-08-22T16:00:00+06:00")
    )
    assert offset_cache.searched_at == NOW
    assert offset_cache.searched_at.tzinfo == UTC


def test_cache_json_round_trip_preserves_request_price_and_stable_id():
    restored = FlightSearchCache.model_validate_json(_cache().model_dump_json())

    assert restored.request == _request()
    assert restored.flights[0].provider_offer_id == "flight_abc"
    assert restored.flights[0].total_price == 714.20
    assert restored.flights[0].adults == 2
    assert restored.status.status == "available"
    assert restored.searched_at == NOW


class _CheckpointState(TypedDict):
    flight_search_cache: FlightSearchCache


def test_sqlite_checkpoint_round_trip_preserves_flight_cache(tmp_path):
    async def run() -> None:
        connection = await aiosqlite.connect(tmp_path / "flight-cache.sqlite")
        saver = AsyncSqliteSaver(connection)
        await saver.setup()
        try:
            graph_builder = StateGraph(_CheckpointState)
            graph_builder.add_node("persist", lambda state: state)
            graph_builder.add_edge(START, "persist")
            graph_builder.add_edge("persist", END)
            graph = graph_builder.compile(checkpointer=saver)
            config = {"configurable": {"thread_id": "flight-cache-thread"}}

            await graph.ainvoke({"flight_search_cache": _cache()}, config=config)
            snapshot = await graph.aget_state(config)
            restored = FlightSearchCache.model_validate(
                snapshot.values["flight_search_cache"]
            )

            assert restored == _cache()
        finally:
            await connection.close()

    asyncio.run(run())
