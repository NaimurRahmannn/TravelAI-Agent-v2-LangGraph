import asyncio
import json
from collections import Counter
from datetime import UTC, datetime

import httpx
import pytest

from app.models import FlightSearchRequest
from app.services.recommendations.base import (
    FlightProviderError,
    FlightProviderUnavailableError,
)
from app.services.recommendations.flights import (
    DuffelAuthenticationError,
    DuffelFlightProvider,
    DuffelPlaceResolutionError,
    DuffelRateLimitError,
    parse_duffel_offer,
    select_duffel_place,
)
from app.services.recommendations.flights.duffel import (
    DUFFEL_SUPPLIER_TIMEOUT_MS,
    MAX_DUFFEL_OFFERS_TO_CONSIDER,
)

FETCHED_AT = datetime(2026, 8, 20, 8, tzinfo=UTC)


def _place(
    name: str,
    code: str,
    *,
    place_type: str = "city",
    country: str = "JP",
    city_name: str | None = None,
) -> dict:
    return {
        "id": f"{place_type}-{code.casefold()}",
        "type": place_type,
        "name": name,
        "iata_code": code,
        "iata_country_code": country,
        "city_name": city_name,
    }


def _segment(
    origin: str,
    destination: str,
    departing_at: str,
    arriving_at: str,
    *,
    carrier: str = "Japan Airlines",
    carrier_code: str = "JL",
    flight_number: str = "101",
) -> dict:
    return {
        "origin": {"iata_code": origin},
        "destination": {"iata_code": destination},
        "departing_at": departing_at,
        "arriving_at": arriving_at,
        "operating_carrier": {
            "name": carrier,
            "iata_code": carrier_code,
        },
        "operating_carrier_flight_number": flight_number,
    }


def _offer(*, live_mode: bool = False, connecting: bool = False) -> dict:
    outbound_segments = [
        _segment(
            "DAC",
            "BKK" if connecting else "NRT",
            "2026-09-10T02:00:00",
            "2026-09-10T05:00:00" if connecting else "2026-09-10T10:00:00",
            carrier="Thai Airways" if connecting else "Japan Airlines",
            carrier_code="TG" if connecting else "JL",
            flight_number="322",
        )
    ]
    if connecting:
        outbound_segments.append(
            _segment(
                "BKK",
                "NRT",
                "2026-09-10T07:00:00",
                "2026-09-10T14:00:00",
                flight_number="643",
            )
        )
    return {
        "id": "off_123",
        "total_amount": "612.40",
        "total_currency": "USD",
        "expires_at": "2026-08-20T09:00:00Z",
        "live_mode": live_mode,
        "owner": {"name": "Japan Airlines", "iata_code": "JL"},
        "slices": [
            {
                "origin": {"iata_code": "DAC"},
                "destination": {"iata_code": "NRT"},
                "duration": "PT12H" if connecting else "PT8H",
                "segments": outbound_segments,
            },
            {
                "origin": {"iata_code": "KIX"},
                "destination": {"iata_code": "DAC"},
                "duration": "PT7H30M",
                "segments": [
                    _segment(
                        "KIX",
                        "DAC",
                        "2026-09-15T18:30:00",
                        "2026-09-16T02:00:00",
                        carrier="Biman Bangladesh Airlines",
                        carrier_code="BG",
                        flight_number="377",
                    )
                ],
            },
        ],
    }


def _search_with_handler(handler):
    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.duffel.com",
        ) as client:
            provider = DuffelFlightProvider(
                "duffel_test_private-token",
                client=client,
                sleep=lambda _: asyncio.sleep(0),
                now=lambda: FETCHED_AT,
            )
            return await provider.search_flights(
                FlightSearchRequest(
                    origin="Dhaka",
                    destination="Tokyo",
                    return_origin="Osaka",
                    return_destination="Dhaka",
                    origin_country_hint="BD",
                    destination_country_hint="JP",
                    return_origin_country_hint="JP",
                    return_destination_country_hint="BD",
                    departure_date="2026-09-10",
                    return_date="2026-09-15",
                    adults=2,
                )
            )

    return asyncio.run(run())


def test_place_selection_prefers_exact_metropolitan_city_over_airport():
    result = select_duffel_place(
        [
            _place("Haneda", "HND", place_type="airport", city_name="Tokyo"),
            _place("Tokyo", "TYO"),
        ],
        query="Tokyo",
    )

    assert result is not None
    assert result.place_type == "city"
    assert result.code == "TYO"


def test_place_selection_accepts_exact_airport_and_country_disambiguates_city():
    airport = select_duffel_place(
        [_place("Heathrow", "LHR", place_type="airport", country="GB")],
        query="Heathrow",
    )
    city = select_duffel_place(
        [
            _place("Springfield", "SPI", country="US"),
            _place("Springfield", "SGF", country="CA"),
        ],
        query="Springfield",
        country_hint="US",
    )

    assert airport is not None and airport.code == "LHR"
    assert city is not None and city.code == "SPI"


def test_place_selection_rejects_ambiguous_exact_matches_without_country_hint():
    result = select_duffel_place(
        [
            _place("Springfield", "SPI", country="US"),
            _place("Springfield", "SGF", country="CA"),
        ],
        query="Springfield",
    )

    assert result is None


def test_search_deduplicates_places_and_builds_bounded_round_trip_request():
    calls = Counter()
    captured_post = {}

    def handler(request: httpx.Request) -> httpx.Response:
        calls[(request.method, request.url.path)] += 1
        assert request.headers["Authorization"] == "Bearer duffel_test_private-token"
        assert request.headers["Duffel-Version"] == "v2"
        assert request.headers["Accept"] == "application/json"
        if request.url.path == "/places/suggestions":
            query = request.url.params["query"]
            places = {
                "Dhaka": [_place("Dhaka", "DAC", country="BD")],
                "Tokyo": [_place("Tokyo", "TYO")],
                "Osaka": [_place("Osaka", "OSA")],
            }
            return httpx.Response(200, json={"data": places[query]})
        if request.method == "POST":
            captured_post["params"] = dict(request.url.params)
            captured_post["body"] = json.loads(request.content)
            captured_post["content_type"] = request.headers["Content-Type"]
            return httpx.Response(
                201,
                json={"data": {"id": "orq_123", "live_mode": False}},
            )
        assert request.url.params["offer_request_id"] == "orq_123"
        assert request.url.params["sort"] == "total_amount"
        assert int(request.url.params["limit"]) == MAX_DUFFEL_OFFERS_TO_CONSIDER
        return httpx.Response(200, json={"data": [_offer()]})

    options = _search_with_handler(handler)

    assert calls[("GET", "/places/suggestions")] == 3
    assert captured_post["params"] == {
        "return_offers": "false",
        "supplier_timeout": str(DUFFEL_SUPPLIER_TIMEOUT_MS),
    }
    assert captured_post["content_type"] == "application/json"
    assert captured_post["body"] == {
        "data": {
            "slices": [
                {
                    "origin": "DAC",
                    "destination": "TYO",
                    "departure_date": "2026-09-10",
                },
                {
                    "origin": "OSA",
                    "destination": "DAC",
                    "departure_date": "2026-09-15",
                },
            ],
            "passengers": [{"type": "adult"}, {"type": "adult"}],
            "cabin_class": "economy",
        }
    }
    assert len(options) == 1
    assert options[0].external_url is None


def test_provider_parses_connections_carriers_prices_expiry_and_test_mode():
    option = parse_duffel_offer(
        _offer(connecting=True),
        fetched_at=FETCHED_AT,
    )

    assert option.total_price == 612.4
    assert option.currency == "USD"
    assert option.total_duration_minutes == 1170
    assert option.stops == 1
    assert option.live_data is False
    assert option.expires_at == datetime(2026, 8, 20, 9, tzinfo=UTC)
    assert option.slices[0].stops == 1
    assert option.slices[1].stops == 0
    assert [
        segment.operating_carrier_name for segment in option.slices[0].segments
    ] == ["Thai Airways", "Japan Airlines"]
    assert option.slices[0].segments[0].flight_number == "322"
    assert option.slices[1].segments[0].operating_carrier_name == (
        "Biman Bangladesh Airlines"
    )


def test_unresolved_place_stops_before_offer_request():
    def handler(request):
        return httpx.Response(200, json={"data": []})

    with pytest.raises(DuffelPlaceResolutionError):
        _search_with_handler(handler)


@pytest.mark.parametrize(
    ("status_code", "error_type", "expected_calls"),
    [
        (401, DuffelAuthenticationError, 1),
        (403, DuffelAuthenticationError, 1),
        (429, DuffelRateLimitError, 3),
        (500, FlightProviderUnavailableError, 3),
        (503, FlightProviderUnavailableError, 3),
    ],
)
def test_place_get_failures_use_bounded_retry_policy(
    status_code,
    error_type,
    expected_calls,
):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status_code, headers={"x-request-id": "req_safe"})

    with pytest.raises(error_type) as error:
        _search_with_handler(handler)

    assert calls == expected_calls
    assert "duffel_test_private-token" not in str(error.value)


def test_offer_request_post_is_not_retried_after_ambiguous_failure():
    post_calls = 0

    def handler(request):
        nonlocal post_calls
        if request.url.path == "/places/suggestions":
            query = request.url.params["query"]
            mapping = {
                "Dhaka": _place("Dhaka", "DAC", country="BD"),
                "Tokyo": _place("Tokyo", "TYO"),
                "Osaka": _place("Osaka", "OSA"),
            }
            return httpx.Response(200, json={"data": [mapping[query]]})
        post_calls += 1
        raise httpx.ReadTimeout("ambiguous")

    with pytest.raises(FlightProviderUnavailableError, match="POST"):
        _search_with_handler(handler)

    assert post_calls == 1


def test_zero_offers_is_a_valid_empty_result():
    def handler(request):
        if request.url.path == "/places/suggestions":
            query = request.url.params["query"]
            mapping = {
                "Dhaka": _place("Dhaka", "DAC", country="BD"),
                "Tokyo": _place("Tokyo", "TYO"),
                "Osaka": _place("Osaka", "OSA"),
            }
            return httpx.Response(200, json={"data": [mapping[query]]})
        if request.method == "POST":
            return httpx.Response(201, json={"data": {"id": "orq_empty"}})
        return httpx.Response(200, json={"data": []})

    assert _search_with_handler(handler) == []


def test_malformed_offer_payload_raises_safe_provider_error():
    with pytest.raises(FlightProviderError, match="Duffel"):
        parse_duffel_offer(
            {"id": "off_bad", "total_amount": "not-money", "slices": []},
            fetched_at=FETCHED_AT,
        )
