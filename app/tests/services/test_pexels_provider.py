import asyncio

import httpx
import pytest

from app.models import ResolvedPlace
from app.services.images import (
    ImageProviderError,
    ImageProviderUnavailableError,
    PexelsAccessError,
    PexelsRateLimitError,
)
from app.services.images.pexels import PexelsImageProvider, build_pexels_query


def _place(**updates) -> ResolvedPlace:
    data = {
        "provider": "geoapify",
        "provider_place_id": "geo-sensoji",
        "name": "Senso-ji Temple",
        "city": "Tokyo",
        "country": "Japan",
        "latitude": 35.7148,
        "longitude": 139.7967,
        "resolution_status": "resolved",
    }
    data.update(updates)
    return ResolvedPlace.model_validate(data)


def _photo(photo_id=12345, **updates):
    photo = {
        "id": photo_id,
        "width": 4000,
        "height": 3000,
        "url": f"https://www.pexels.com/photo/sensoji-{photo_id}/",
        "photographer": "Jane Doe",
        "photographer_url": "https://www.pexels.com/@jane-doe/",
        "alt": "Senso-ji Temple in Tokyo",
        "src": {
            "original": f"https://images.pexels.com/photos/{photo_id}/photo.jpeg",
            "large": f"https://images.pexels.com/photos/{photo_id}/large.jpeg",
        },
    }
    photo.update(updates)
    return photo


def _provider(handler, *, sleep=None):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    kwargs = {"client": client}
    if sleep is not None:
        kwargs["sleep"] = sleep
    return PexelsImageProvider("pexels-test-key", **kwargs), client


def test_build_pexels_query_uses_trusted_place_context():
    assert build_pexels_query(_place()) == "Senso-ji Temple, Tokyo, Japan"
    assert build_pexels_query(_place(city="Japan")) == "Senso-ji Temple, Japan"


def test_provider_searches_with_api_key_and_returns_attribution_ready_image():
    def handler(request: httpx.Request):
        assert request.headers["Authorization"] == "pexels-test-key"
        assert request.url.params["query"] == "Senso-ji Temple, Tokyo, Japan"
        assert request.url.params["per_page"] == "10"
        return httpx.Response(200, json={"photos": [_photo()]})

    provider, client = _provider(handler)
    try:
        image = asyncio.run(provider.resolve_image(place=_place()))
    finally:
        asyncio.run(client.aclose())

    assert image is not None
    assert image.provider == "pexels"
    assert image.provider_image_id == "12345"
    assert image.author == "Jane Doe"
    assert image.attribution_text == "Photo by Jane Doe on Pexels"


def test_provider_skips_unsafe_results_and_uses_next_safe_photo():
    unsafe = _photo()
    unsafe["src"]["original"] = "https://evil.example/photo.jpeg"

    def handler(request: httpx.Request):
        return httpx.Response(200, json={"photos": [unsafe, _photo(67890)]})

    provider, client = _provider(handler)
    try:
        image = asyncio.run(provider.resolve_image(place=_place()))
    finally:
        asyncio.run(client.aclose())

    assert image is not None
    assert image.provider_image_id == "67890"


def test_provider_returns_none_when_search_has_no_safe_results():
    def handler(request: httpx.Request):
        return httpx.Response(200, json={"photos": []})

    provider, client = _provider(handler)
    try:
        assert asyncio.run(provider.resolve_image(place=_place())) is None
    finally:
        asyncio.run(client.aclose())


@pytest.mark.parametrize("status", [401, 403])
def test_provider_reports_rejected_api_key(status):
    def handler(request: httpx.Request):
        return httpx.Response(status)

    provider, client = _provider(handler)
    try:
        with pytest.raises(PexelsAccessError):
            asyncio.run(provider.resolve_image(place=_place()))
    finally:
        asyncio.run(client.aclose())


def test_provider_retries_rate_limit_then_succeeds():
    attempts = 0
    delays = []

    def handler(request: httpx.Request):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"photos": [_photo()]})

    async def sleep(delay):
        delays.append(delay)

    provider, client = _provider(handler, sleep=sleep)
    try:
        image = asyncio.run(provider.resolve_image(place=_place()))
    finally:
        asyncio.run(client.aclose())

    assert image is not None
    assert attempts == 3
    assert delays == [0.0, 0.0]


@pytest.mark.parametrize(
    ("status", "error_type"),
    [(429, PexelsRateLimitError), (503, ImageProviderUnavailableError)],
)
def test_provider_fails_safely_after_bounded_retries(status, error_type):
    attempts = 0

    def handler(request: httpx.Request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(status, headers={"Retry-After": "0"})

    async def sleep(delay):
        return None

    provider, client = _provider(handler, sleep=sleep)
    try:
        with pytest.raises(error_type):
            asyncio.run(provider.resolve_image(place=_place()))
    finally:
        asyncio.run(client.aclose())

    assert attempts == 3


def test_provider_rejects_invalid_json():
    def handler(request: httpx.Request):
        return httpx.Response(200, content=b"not-json")

    provider, client = _provider(handler)
    try:
        with pytest.raises(ImageProviderError):
            asyncio.run(provider.resolve_image(place=_place()))
    finally:
        asyncio.run(client.aclose())
