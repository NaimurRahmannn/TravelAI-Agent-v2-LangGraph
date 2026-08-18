import asyncio
import logging

import httpx
import pytest

from app.services.places.geoapify import (
    GeoapifyAuthenticationError,
    GeoapifyPlacesProvider,
    GeoapifyProviderError,
    GeoapifyRateLimitError,
    select_geoapify_candidate,
)


def _candidate(
    *,
    name: str = "Wat Mahathat",
    city: str = "Ayutthaya",
    country: str = "Thailand",
    confidence: float = 0.95,
    place_id: str = "place-1",
) -> dict:
    return {
        "place_id": place_id,
        "name": name,
        "formatted": f"{name}, {city}, {country}",
        "city": city,
        "state": city,
        "country": country,
        "country_code": "th" if country == "Thailand" else "jp",
        "lat": 14.3569,
        "lon": 100.5683,
        "category": "tourism.sights",
        "result_type": "amenity",
        "rank": {"confidence": confidence},
        "datasource": {"attribution": "OpenStreetMap contributors"},
    }


def _resolve_with_handler(handler, *, api_key="test-geo-key"):
    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            provider = GeoapifyPlacesProvider(
                api_key,
                client=client,
                sleep=lambda _: _no_sleep(),
            )
            return await provider.resolve_place(
                name="Wat Mahathat",
                location_hint="Ayutthaya, Thailand",
                city="Ayutthaya",
                destination="Thailand",
            )

    return asyncio.run(run())


async def _no_sleep():
    return None


def test_successful_result_parses_provider_fields_and_passes_api_key():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"results": [_candidate()]})

    resolution = _resolve_with_handler(handler)

    assert resolution.status == "resolved"
    assert resolution.place.provider_place_id == "place-1"
    assert resolution.place.categories == ["tourism.sights"]
    assert resolution.place.source_attribution == "OpenStreetMap contributors"
    assert requests[0].url.params["apiKey"] == "test-geo-key"
    assert requests[0].url.params["limit"] == "5"
    assert "type" not in requests[0].url.params


def test_empty_results_are_unresolved():
    resolution = _resolve_with_handler(
        lambda request: httpx.Response(200, json={"results": []})
    )

    assert resolution.status == "unresolved"
    assert resolution.place is None


def test_multiple_candidates_prefer_matching_city_and_country():
    candidates = [
        _candidate(city="Bangkok", confidence=0.99, place_id="wrong-city"),
        _candidate(city="Ayutthaya", confidence=0.82, place_id="correct"),
        _candidate(country="Japan", city="Kyoto", place_id="wrong-country"),
    ]

    resolution = select_geoapify_candidate(
        candidates,
        name="Wat Mahathat",
        city="Ayutthaya",
        destination="Thailand",
    )

    assert resolution.status == "resolved"
    assert resolution.place.provider_place_id == "correct"


def test_famous_attraction_can_resolve_with_low_provider_confidence():
    resolution = select_geoapify_candidate(
        [_candidate(confidence=0.2)],
        name="Wat Mahathat",
        city="Ayutthaya",
        destination="Thailand",
    )

    assert resolution.status == "resolved"


def test_plausible_weaker_name_match_is_partial():
    resolution = select_geoapify_candidate(
        [_candidate(name="Forest Temple", city="", confidence=0.2)],
        name="Hidden Forest Temple",
        city="Kanchanaburi",
        destination="Thailand",
    )

    assert resolution.status == "partially_resolved"


def test_clearly_wrong_country_candidate_is_unresolved():
    resolution = select_geoapify_candidate(
        [_candidate(country="Japan", city="Kyoto")],
        name="Wat Mahathat",
        city="Ayutthaya",
        destination="Thailand",
    )

    assert resolution.status == "unresolved"


@pytest.mark.parametrize(
    ("name", "city"),
    [
        ("Erawan National Park", "Kanchanaburi"),
        ("Bridge over the River Kwai", "Kanchanaburi"),
    ],
)
def test_named_thailand_landmarks_resolve_deterministically(name, city):
    resolution = select_geoapify_candidate(
        [_candidate(name=name, city=city, confidence=0.7)],
        name=name,
        city=city,
        destination="Thailand",
    )

    assert resolution.status == "resolved"
    assert resolution.place.name == name


@pytest.mark.parametrize(
    ("status_code", "error_type", "expected_calls"),
    [
        (401, GeoapifyAuthenticationError, 1),
        (403, GeoapifyAuthenticationError, 1),
        (429, GeoapifyRateLimitError, 3),
        (500, GeoapifyProviderError, 3),
    ],
)
def test_http_errors_follow_retry_policy(status_code, error_type, expected_calls):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status_code, json={"message": "provider error"})

    with pytest.raises(error_type):
        _resolve_with_handler(handler)

    assert calls == expected_calls


@pytest.mark.parametrize("error", [httpx.ReadTimeout("timeout"), httpx.ConnectError("down")])
def test_transport_errors_retry_and_raise_safe_error(error):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        raise error

    with pytest.raises(GeoapifyProviderError, match="Geoapify request failed"):
        _resolve_with_handler(handler)

    assert calls == 3


def test_retryable_failure_then_success():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, json={})
        return httpx.Response(200, json={"results": [_candidate()]})

    assert _resolve_with_handler(handler).status == "resolved"
    assert calls == 2


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={"unexpected": []}),
    ],
)
def test_invalid_or_unexpected_payload_raises_safe_error(response):
    with pytest.raises(GeoapifyProviderError):
        _resolve_with_handler(lambda request: response)


def test_api_key_never_appears_in_logs_or_error(caplog):
    secret = "geo-secret-do-not-log"
    caplog.set_level(logging.INFO)

    with pytest.raises(GeoapifyAuthenticationError) as captured:
        _resolve_with_handler(
            lambda request: httpx.Response(401, json={"apiKey": secret}),
            api_key=secret,
        )

    assert secret not in caplog.text
    assert secret not in str(captured.value)
