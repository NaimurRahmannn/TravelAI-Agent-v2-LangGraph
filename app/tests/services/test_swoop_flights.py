import asyncio
from datetime import UTC, datetime

import pytest
from swoop import (
    Itinerary,
    Layover,
    SearchResult,
    Segment,
    SwoopHTTPError,
    SwoopParseError,
    SwoopRateLimitError,
    SwoopUpstreamError,
    TripLeg,
    TripOption,
)

from app.models import FlightSearchRequest
from app.services.recommendations.base import (
    FlightProviderError,
    FlightProviderUnavailableError,
)
from app.services.recommendations.flights.swoop import (
    MAX_SWOOP_RESULTS_TO_CONSIDER,
    SWOOP_POINT_OF_SALE_COUNTRY,
    SWOOP_RETRIES,
    SWOOP_TIMEOUT_SECONDS,
    SwoopFlightProvider,
    parse_swoop_option,
)

FETCHED_AT = datetime(2026, 8, 20, 8, tzinfo=UTC)


@pytest.fixture(autouse=True)
def dispatch_thread_calls_inline(monkeypatch):
    async def inline_to_thread(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(
        "app.services.recommendations.flights.swoop.asyncio.to_thread",
        inline_to_thread,
    )


class Resolver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.codes = {
            "Dhaka": "DAC",
            "Tokyo": "HND",
            "Osaka": "KIX",
        }

    async def resolve_airport(self, query, *, country_hint=None):
        self.calls.append((query, country_hint))
        return self.codes.get(query, query)


def _segment(
    origin: str,
    destination: str,
    *,
    departure_date: tuple[int, int, int],
    departure_time: tuple[int, int],
    arrival_date: tuple[int, int, int],
    arrival_time: tuple[int, int],
    duration: int,
    airline: str = "QR",
    airline_name: str = "Qatar Airways",
    flight_number: str = "641",
) -> Segment:
    return Segment(
        airline=airline,
        airline_name=airline_name,
        flight_number=flight_number,
        operator=airline_name,
        aircraft="Boeing 777",
        departure_airport_code=origin,
        arrival_airport_code=destination,
        departure_date=departure_date,
        departure_time=departure_time,
        arrival_date=arrival_date,
        arrival_time=arrival_time,
        travel_time=duration,
    )


def _leg(
    origin: str,
    destination: str,
    date: str,
    *,
    connecting: bool = False,
    return_leg: bool = False,
) -> TripLeg:
    calendar_date = tuple(int(value) for value in date.split("-"))
    if connecting:
        first = _segment(
            origin,
            "DOH",
            departure_date=calendar_date,
            departure_time=(9, 30),
            arrival_date=calendar_date,
            arrival_time=(13, 0),
            duration=270,
        )
        second = _segment(
            "DOH",
            destination,
            departure_date=calendar_date,
            departure_time=(14, 30),
            arrival_date=(2026, 9, 11),
            arrival_time=(7, 20),
            duration=650,
            airline="JL",
            airline_name="Japan Airlines",
            flight_number="50",
        )
        itinerary = Itinerary(
            airline_code="QR",
            airline_names=["Qatar Airways", "Japan Airlines"],
            segments=[first, second],
            layovers=[
                Layover(
                    minutes=90,
                    departure_airport_code="DOH",
                    departure_airport_name="Hamad International Airport",
                    departure_airport_city="Doha",
                )
            ],
            travel_time=1010,
            stop_count=1,
        )
    else:
        departure_time = (18, 10) if return_leg else (9, 30)
        arrival_time = (3, 20) if return_leg else (15, 30)
        arrival_date = (2026, 9, 16) if return_leg else calendar_date
        itinerary = Itinerary(
            airline_code="BG",
            airline_names=["Biman Bangladesh Airlines"],
            segments=[
                _segment(
                    origin,
                    destination,
                    departure_date=calendar_date,
                    departure_time=departure_time,
                    arrival_date=arrival_date,
                    arrival_time=arrival_time,
                    duration=430,
                    airline="BG",
                    airline_name="Biman Bangladesh Airlines",
                    flight_number="377",
                )
            ],
            travel_time=430,
            stop_count=0,
        )
    return TripLeg(
        origin=origin,
        destination=destination,
        date=date,
        itinerary=itinerary,
    )


def _option(
    *,
    price: float = 714.20,
    currency: str = "USD",
    open_jaw: bool = False,
    selector: str = "opaque-provider-selector",
) -> TripOption:
    return TripOption(
        selector=selector,
        price=price,
        currency=currency,
        legs=[
            _leg("DAC", "HND", "2026-09-10", connecting=True),
            _leg(
                "KIX" if open_jaw else "HND",
                "DAC",
                "2026-09-15",
                return_leg=True,
            ),
        ],
    )


def _request(*, open_jaw: bool = False, one_way: bool = False):
    return FlightSearchRequest(
        origin="Dhaka",
        destination="Tokyo",
        return_origin="Osaka" if open_jaw else "Tokyo",
        return_destination="Dhaka",
        origin_country_hint="BD",
        destination_country_hint="JP",
        return_origin_country_hint="JP",
        return_destination_country_hint="BD",
        departure_date="2026-09-10",
        return_date=None if one_way else "2026-09-15",
        adults=2,
    )


def test_round_trip_uses_passenger_aware_search_and_does_not_multiply_total():
    captured = {}

    def search_function(origin, destination, date, **kwargs):
        captured.update(
            origin=origin,
            destination=destination,
            date=date,
            kwargs=kwargs,
        )
        return SearchResult(results=[_option()])

    provider = SwoopFlightProvider(Resolver(), search_function=search_function)
    option = asyncio.run(provider.search_flights(_request()))[0]

    assert captured["origin"] == "DAC"
    assert captured["destination"] == "HND"
    assert captured["date"] == "2026-09-10"
    assert captured["kwargs"]["return_date"] == "2026-09-15"
    assert captured["kwargs"]["passengers"].adults == 2
    assert captured["kwargs"]["passengers"].children == 0
    assert captured["kwargs"]["cabin"] == "economy"
    transport = captured["kwargs"]["transport"]
    assert transport.country == SWOOP_POINT_OF_SALE_COUNTRY
    assert transport.timeout == SWOOP_TIMEOUT_SECONDS
    assert transport.retries == SWOOP_RETRIES
    assert option.total_price == 714.20
    assert option.adults == 2
    assert option.price_type == "shopping_total"
    assert option.total_price != 1428.40


def test_swoop_option_maps_segments_layovers_airlines_stops_and_duration():
    option = parse_swoop_option(_option(), adults=2, fetched_at=FETCHED_AT)

    assert option.provider == "swoop"
    assert option.origin_code == "DAC"
    assert option.destination_code == "HND"
    assert option.airline_names == [
        "Qatar Airways",
        "Japan Airlines",
        "Biman Bangladesh Airlines",
    ]
    assert option.total_duration_minutes == 1440
    assert option.stops == 1
    assert len(option.slices) == 2
    assert option.slices[0].stops == 1
    assert option.slices[1].stops == 0
    assert option.slices[0].segments[1].flight_number == "50"
    assert option.slices[0].segments[1].aircraft == "Boeing 777"
    assert option.slices[0].layovers[0].airport_code == "DOH"
    assert option.slices[0].layovers[0].duration_minutes == 90
    assert "opaque-provider-selector" not in option.model_dump_json()


def test_provider_id_is_sha256_stable_and_does_not_expose_selector():
    first = parse_swoop_option(_option(selector="one"), adults=2, fetched_at=FETCHED_AT)
    second = parse_swoop_option(_option(selector="two"), adults=2, fetched_at=FETCHED_AT)

    assert first.provider_offer_id == second.provider_offer_id
    assert first.provider_offer_id.startswith("swoop_")
    assert len(first.provider_offer_id) == len("swoop_") + 64


def test_itinerary_airline_names_survive_missing_segment_labels():
    raw_option = _option()
    outbound = raw_option.legs[0].itinerary
    assert outbound is not None
    for segment in outbound.segments:
        segment.airline_name = ""
        segment.operator = ""

    option = parse_swoop_option(raw_option, adults=2, fetched_at=FETCHED_AT)

    assert "Qatar Airways" in option.airline_names
    assert "Japan Airlines" in option.airline_names


def test_one_way_search_returns_one_slice():
    def search_function(*args, **kwargs):
        assert "return_date" not in kwargs
        return SearchResult(
            results=[
                TripOption(
                    selector="one-way",
                    price=400,
                    currency="USD",
                    legs=[_leg("DAC", "HND", "2026-09-10")],
                )
            ]
        )

    provider = SwoopFlightProvider(Resolver(), search_function=search_function)
    result = asyncio.run(provider.search_flights(_request(one_way=True)))

    assert len(result[0].slices) == 1
    assert result[0].total_price == 400


def test_open_jaw_uses_one_multi_leg_search_without_adding_leg_prices():
    captured = {}

    def fail_search(*args, **kwargs):
        raise AssertionError("open-jaw search must not call search()")

    def search_legs_function(legs, **kwargs):
        captured["legs"] = legs
        captured["kwargs"] = kwargs
        return SearchResult(results=[_option(open_jaw=True, price=820)])

    provider = SwoopFlightProvider(
        Resolver(),
        search_function=fail_search,
        search_legs_function=search_legs_function,
    )
    option = asyncio.run(provider.search_flights(_request(open_jaw=True)))[0]

    assert [
        (leg.from_airport, leg.to_airport, leg.date)
        for leg in captured["legs"]
    ] == [
        ("DAC", "HND", "2026-09-10"),
        ("KIX", "DAC", "2026-09-15"),
    ]
    assert option.total_price == 820
    assert option.slices[1].origin_code == "KIX"


def test_sync_search_is_dispatched_through_asyncio_to_thread(monkeypatch):
    calls = []

    async def fake_to_thread(function, *args, **kwargs):
        calls.append(function)
        return function(*args, **kwargs)

    monkeypatch.setattr(
        "app.services.recommendations.flights.swoop.asyncio.to_thread",
        fake_to_thread,
    )
    provider = SwoopFlightProvider(
        Resolver(),
        search_function=lambda *args, **kwargs: SearchResult(results=[]),
    )

    assert asyncio.run(provider.search_flights(_request())) == []
    assert len(calls) == 1


def test_successful_empty_search_is_not_an_upstream_failure():
    provider = SwoopFlightProvider(
        Resolver(),
        search_function=lambda *args, **kwargs: SearchResult(results=[]),
    )

    assert asyncio.run(provider.search_flights(_request())) == []


@pytest.mark.parametrize(
    "error",
    [
        SwoopRateLimitError(),
        SwoopHTTPError(503),
        SwoopParseError("invalid response"),
        SwoopUpstreamError(13),
        TimeoutError("timed out"),
    ],
)
def test_swoop_failures_map_to_provider_unavailable(error):
    def fail(*args, **kwargs):
        raise error

    provider = SwoopFlightProvider(Resolver(), search_function=fail)

    with pytest.raises(FlightProviderUnavailableError, match="temporarily"):
        asyncio.run(provider.search_flights(_request()))


def test_result_processing_is_bounded():
    options = [
        _option(price=500 + index, selector=str(index))
        for index in range(MAX_SWOOP_RESULTS_TO_CONSIDER + 5)
    ]
    provider = SwoopFlightProvider(
        Resolver(),
        search_function=lambda *args, **kwargs: SearchResult(results=options),
    )

    normalized = asyncio.run(provider.search_flights(_request()))

    assert len(normalized) == MAX_SWOOP_RESULTS_TO_CONSIDER


def test_malformed_option_and_invalid_currency_fail_safely():
    malformed = _option(currency="US dollars")
    provider = SwoopFlightProvider(
        Resolver(),
        search_function=lambda *args, **kwargs: SearchResult(results=[malformed]),
    )

    with pytest.raises(FlightProviderError, match="no valid"):
        asyncio.run(provider.search_flights(_request()))


def test_non_usd_currency_remains_available_for_budget_unknown_handling():
    provider = SwoopFlightProvider(
        Resolver(),
        search_function=lambda *args, **kwargs: SearchResult(
            results=[_option(currency="EUR")]
        ),
    )

    option = asyncio.run(provider.search_flights(_request()))[0]

    assert option.currency == "EUR"
    assert option.total_price == 714.20


def test_request_local_airport_resolution_deduplicates_repeated_endpoints():
    resolver = Resolver()
    provider = SwoopFlightProvider(
        resolver,
        search_function=lambda *args, **kwargs: SearchResult(results=[]),
    )

    asyncio.run(provider.search_flights(_request()))

    assert resolver.calls == [("Dhaka", "BD"), ("Tokyo", "JP")]
