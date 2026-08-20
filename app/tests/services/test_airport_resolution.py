import asyncio

import httpx
import pytest

from app.services.recommendations.flights.airport_resolution import (
    AirportCandidate,
    AirportResolutionError,
    GeoapifyAirportResolver,
    select_airport_candidate,
)


def _city(name: str, country: str, lat: float, lon: float) -> dict:
    return {
        "city": name,
        "name": name,
        "country_code": country,
        "lat": lat,
        "lon": lon,
        "place_id": f"city-{name.casefold()}",
        "rank": {"confidence": 0.95},
    }


def _airport_feature(
    place_id: str,
    *,
    city: str,
    country: str,
    distance: int,
    international: bool = True,
) -> dict:
    return {
        "type": "Feature",
        "properties": {
            "place_id": place_id,
            "city": city,
            "country_code": country,
            "distance": distance,
            "categories": [
                "airport.international" if international else "airport"
            ],
        },
    }


def _details(
    iata: str | None,
    *,
    city: str,
    country: str,
) -> dict:
    airport = {"closest_town": city}
    if iata is not None:
        airport["iata"] = iata
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "feature_type": "details",
                    "city": city,
                    "country_code": country,
                    "airport": airport,
                },
            }
        ],
    }


def _resolver(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GeoapifyAirportResolver(
        "private-geoapify-key",
        client=client,
        sleep=lambda _: asyncio.sleep(0),
    ), client


def test_existing_iata_bypasses_geoapify_lookup():
    def handler(request):
        raise AssertionError("Geoapify must not be called for direct IATA input")

    resolver, client = _resolver(handler)
    try:
        assert asyncio.run(resolver.resolve_airport(" dac ")) == "DAC"
    finally:
        asyncio.run(client.aclose())


@pytest.mark.parametrize(
    ("query", "country", "iata", "lat", "lon"),
    [
        ("Dhaka", "BD", "DAC", 23.81, 90.41),
        ("Tokyo", "JP", "HND", 35.68, 139.76),
        ("Osaka", "JP", "KIX", 34.69, 135.50),
    ],
)
def test_city_resolves_to_geoapify_airport_iata(query, country, iata, lat, lon):
    def handler(request: httpx.Request):
        if request.url.path.endswith("/geocode/search"):
            assert request.url.params["type"] == "city"
            return httpx.Response(200, json={"results": [_city(query, country, lat, lon)]})
        if request.url.path.endswith("/places"):
            assert request.url.params["categories"] == (
                "airport.international,airport"
            )
            return httpx.Response(
                200,
                json={
                    "features": [
                        _airport_feature(
                            f"airport-{iata}",
                            city=query,
                            country=country,
                            distance=20_000,
                        )
                    ]
                },
            )
        return httpx.Response(200, json=_details(iata, city=query, country=country))

    resolver, client = _resolver(handler)
    try:
        assert asyncio.run(
            resolver.resolve_airport(query, country_hint=country)
        ) == iata
    finally:
        asyncio.run(client.aclose())


def test_country_mismatch_is_rejected():
    def handler(request: httpx.Request):
        if request.url.path.endswith("/geocode/search"):
            return httpx.Response(
                200,
                json={"results": [_city("Tokyo", "JP", 35.68, 139.76)]},
            )
        if request.url.path.endswith("/places"):
            return httpx.Response(
                200,
                json={
                    "features": [
                        _airport_feature(
                            "wrong-country",
                            city="Tokyo",
                            country="US",
                            distance=100,
                        )
                    ]
                },
            )
        return httpx.Response(200, json=_details("LAX", city="Tokyo", country="US"))

    resolver, client = _resolver(handler)
    try:
        with pytest.raises(AirportResolutionError, match="No trusted airport"):
            asyncio.run(resolver.resolve_airport("Tokyo", country_hint="JP"))
    finally:
        asyncio.run(client.aclose())


def test_candidate_without_airport_iata_is_rejected():
    def handler(request: httpx.Request):
        if request.url.path.endswith("/geocode/search"):
            return httpx.Response(
                200,
                json={"results": [_city("Dhaka", "BD", 23.81, 90.41)]},
            )
        if request.url.path.endswith("/places"):
            return httpx.Response(
                200,
                json={
                    "features": [
                        _airport_feature(
                            "airport-no-iata",
                            city="Dhaka",
                            country="BD",
                            distance=100,
                        )
                    ]
                },
            )
        return httpx.Response(200, json=_details(None, city="Dhaka", country="BD"))

    resolver, client = _resolver(handler)
    try:
        with pytest.raises(AirportResolutionError):
            asyncio.run(resolver.resolve_airport("Dhaka", country_hint="BD"))
    finally:
        asyncio.run(client.aclose())


def test_international_and_city_match_preferences_are_deterministic():
    candidates = [
        AirportCandidate("NRT", "JP", ("airport.international",), "Narita", "Narita", 5000),
        AirportCandidate("HND", "JP", ("airport.international",), "Tokyo", "Tokyo", 20000),
        AirportCandidate("AAA", "JP", ("airport",), "Tokyo", "Tokyo", 100),
    ]

    selected = select_airport_candidate(
        candidates,
        requested_city="Tokyo",
        country_code="JP",
    )

    assert selected is not None and selected.iata == "HND"


def test_stable_iata_tie_break_is_used_for_equivalent_candidates():
    candidates = [
        AirportCandidate("ZZZ", "JP", ("airport.international",), "Osaka", "Osaka", 1000),
        AirportCandidate("KIX", "JP", ("airport.international",), "Osaka", "Osaka", 1000),
    ]

    selected = select_airport_candidate(
        candidates,
        requested_city="Osaka",
        country_code="JP",
    )

    assert selected is not None and selected.iata == "KIX"


def test_resolution_is_deduplicated_within_resolver_operation():
    calls = []

    def handler(request: httpx.Request):
        calls.append(request.url.path)
        if request.url.path.endswith("/geocode/search"):
            return httpx.Response(
                200,
                json={"results": [_city("Dhaka", "BD", 23.81, 90.41)]},
            )
        if request.url.path.endswith("/places"):
            return httpx.Response(
                200,
                json={
                    "features": [
                        _airport_feature(
                            "airport-DAC",
                            city="Dhaka",
                            country="BD",
                            distance=10_000,
                        )
                    ]
                },
            )
        return httpx.Response(200, json=_details("DAC", city="Dhaka", country="BD"))

    resolver, client = _resolver(handler)
    try:
        async def resolve_twice():
            first = await resolver.resolve_airport("Dhaka", country_hint="BD")
            second = await resolver.resolve_airport("Dhaka", country_hint="BD")
            return first, second

        assert asyncio.run(resolve_twice()) == ("DAC", "DAC")
        assert len(calls) == 3
    finally:
        asyncio.run(client.aclose())


@pytest.mark.parametrize("status", [429, 500])
def test_geoapify_failure_is_bounded_and_safe(status):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status)

    resolver, client = _resolver(handler)
    try:
        with pytest.raises(AirportResolutionError, match="temporarily"):
            asyncio.run(resolver.resolve_airport("Dhaka", country_hint="BD"))
        assert calls == 2
    finally:
        asyncio.run(client.aclose())
