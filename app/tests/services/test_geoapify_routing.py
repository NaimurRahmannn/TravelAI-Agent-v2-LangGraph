import asyncio

import httpx
import pytest

from app.services.routing import (
    GeoapifyRoutingProvider,
    RoutingAuthenticationError,
    RoutingProviderError,
    RoutingRateLimitError,
)
from app.services.routing.geoapify import parse_geoapify_route


def test_route_request_uses_pair_mode_metric_units_and_parses_leg_metrics():
    seen_request: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = request
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "distance": 9999,
                        "time": 9999,
                        "legs": [{"distance": 1280.5, "time": 615.4}],
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GeoapifyRoutingProvider(
        "private-key",
        client=client,
        min_request_interval_seconds=0,
    )

    result = asyncio.run(
        provider.get_route(
            origin_latitude=13.7563,
            origin_longitude=100.5018,
            destination_latitude=13.7437,
            destination_longitude=100.4889,
            mode="transit",
        )
    )
    asyncio.run(client.aclose())

    assert result is not None
    assert result.distance_meters == 1280.5
    assert result.duration_seconds == 615
    assert seen_request is not None
    assert seen_request.url.params["waypoints"] == "13.7563,100.5018|13.7437,100.4889"
    assert seen_request.url.params["mode"] == "transit"
    assert seen_request.url.params["format"] == "json"
    assert seen_request.url.params["units"] == "metric"
    assert seen_request.url.params["apiKey"] == "private-key"


def test_empty_results_are_a_normal_unavailable_route():
    assert parse_geoapify_route({"results": []}) is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"results": [None]},
        {"results": [{}]},
        {"results": [{"distance": -1, "time": 20}]},
    ],
)
def test_malformed_route_payload_is_rejected(payload):
    with pytest.raises(RoutingProviderError):
        parse_geoapify_route(payload)


def test_rate_limit_retries_retry_after_then_raises():
    calls = 0
    delays: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "0.1"})

    async def sleep(delay: float) -> None:
        delays.append(delay)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GeoapifyRoutingProvider(
        "private-key",
        client=client,
        sleep=sleep,
        min_request_interval_seconds=0,
    )

    with pytest.raises(RoutingRateLimitError):
        asyncio.run(
            provider.get_route(
                origin_latitude=1,
                origin_longitude=2,
                destination_latitude=3,
                destination_longitude=4,
                mode="drive",
            )
        )
    asyncio.run(client.aclose())

    assert calls == 3
    assert delays == [0.1, 0.1]


def test_authentication_failure_is_not_retried():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GeoapifyRoutingProvider(
        "private-key",
        client=client,
        min_request_interval_seconds=0,
    )

    with pytest.raises(RoutingAuthenticationError):
        asyncio.run(
            provider.get_route(
                origin_latitude=1,
                origin_longitude=2,
                destination_latitude=3,
                destination_longitude=4,
                mode="walk",
            )
        )
    asyncio.run(client.aclose())

    assert calls == 1
