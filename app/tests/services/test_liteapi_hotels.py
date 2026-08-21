import asyncio
import json
from datetime import UTC, date, datetime

import httpx
import pytest

from app.models import HotelSearchRequest
from app.services.recommendations.hotels.liteapi import (
    LiteApiAuthenticationError,
    LiteApiHotelProvider,
    LiteApiResponseError,
)


def _request() -> HotelSearchRequest:
    return HotelSearchRequest(
        city="Tokyo",
        latitude=35.6762,
        longitude=139.6503,
        check_in=date(2026, 9, 10),
        check_out=date(2026, 9, 13),
        adults=2,
        guest_nationality_country_code="BD",
        radius_meters=5_000,
    )


def _response() -> dict:
    return {
        "sandbox": True,
        "data": [
            {
                "hotelId": "hotel-1",
                "roomTypes": [
                    {
                        "offerId": "offer-480",
                        "rates": [
                            {
                                "name": "Deluxe Double Room",
                                "boardName": "Breakfast Included",
                                "retailRate": {
                                    "total": [
                                        {"currency": "EUR", "amount": 450},
                                        {"currency": "USD", "amount": "480.00"},
                                    ],
                                    "taxesAndFees": [{"included": True}],
                                },
                                "cancellationPolicies": {
                                    "refundableTag": "RFN"
                                },
                            }
                        ],
                    }
                ],
            }
        ],
        "hotels": [
            {
                "id": "hotel-1",
                "name": "Hotel Sakura",
                "address": "1-2-3 Shinjuku, Tokyo",
                "city": "Tokyo",
                "country": "Japan",
                "latitude": 35.69,
                "longitude": 139.70,
                "rating": 8.7,
                "reviewCount": 0,
                "main_photo": "https://images.example.test/hotel.jpg",
            }
        ],
    }


def test_rates_request_and_response_normalization_preserve_total_stay_semantics():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = request.headers
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_response())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = LiteApiHotelProvider(
        "test-secret",
        client=client,
        now=lambda: datetime(2026, 8, 21, tzinfo=UTC),
    )
    hotels = asyncio.run(provider.search_hotels(_request()))
    asyncio.run(client.aclose())

    assert captured["headers"]["X-API-Key"] == "test-secret"
    assert captured["body"] == {
        "occupancies": [{"adults": 2}],
        "currency": "USD",
        "guestNationality": "BD",
        "checkin": "2026-09-10",
        "checkout": "2026-09-13",
        "latitude": 35.6762,
        "longitude": 139.6503,
        "radius": 5000,
        "roomMapping": True,
        "maxRatesPerHotel": 1,
        "includeHotelData": True,
        "limit": 20,
    }
    hotel = hotels[0]
    assert hotel.provider == "liteapi"
    assert hotel.provider_hotel_id == "hotel-1"
    assert hotel.provider_offer_id == "offer-480"
    assert hotel.stay_key.startswith("stay_")
    assert hotel.name == "Hotel Sakura"
    assert hotel.formatted_address == "1-2-3 Shinjuku, Tokyo"
    assert hotel.latitude == 35.69
    assert hotel.longitude == 139.70
    assert hotel.rating == 8.7
    assert hotel.review_count == 0
    assert hotel.total_price == 480
    assert hotel.price_per_night == 160
    assert hotel.room_name == "Deluxe Double Room"
    assert hotel.board_name == "Breakfast Included"
    assert hotel.refundable is True
    assert hotel.taxes_included is True
    assert hotel.is_sandbox is True
    assert hotel.external_url is None


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_statuses_retry_once_then_succeed(status):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(status)
        return httpx.Response(200, json={"data": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = LiteApiHotelProvider(
        "secret",
        client=client,
        sleep=lambda _: asyncio.sleep(0),
    )
    assert asyncio.run(provider.search_hotels(_request())) == []
    asyncio.run(client.aclose())
    assert calls == 2


def test_transport_timeout_retries_once():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("timed out", request=request)
        return httpx.Response(200, json={"data": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = LiteApiHotelProvider(
        "secret",
        client=client,
        sleep=lambda _: asyncio.sleep(0),
    )
    assert asyncio.run(provider.search_hotels(_request())) == []
    asyncio.run(client.aclose())
    assert calls == 2


@pytest.mark.parametrize("status", [401, 403])
def test_authentication_failures_are_not_retried(status):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = LiteApiHotelProvider("secret", client=client)
    with pytest.raises(LiteApiAuthenticationError):
        asyncio.run(provider.search_hotels(_request()))
    asyncio.run(client.aclose())
    assert calls == 1


def test_bad_request_is_not_retried():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = LiteApiHotelProvider("secret", client=client)
    with pytest.raises(LiteApiResponseError):
        asyncio.run(provider.search_hotels(_request()))
    asyncio.run(client.aclose())
    assert calls == 1


def test_malformed_success_response_is_rejected():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"unexpected": []})
        )
    )
    provider = LiteApiHotelProvider("secret", client=client)
    with pytest.raises(LiteApiResponseError):
        asyncio.run(provider.search_hotels(_request()))
    asyncio.run(client.aclose())
