import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from app.core.logging import get_logger
from app.models import PlaceImage, ResolvedPlace
from app.services.images.base import (
    ImageProviderError,
    ImageProviderUnavailableError,
    PexelsAccessError,
    PexelsRateLimitError,
)

logger = get_logger(__name__)

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"
PEXELS_LICENSE_URL = "https://www.pexels.com/license/"
PEXELS_RESULT_LIMIT = 10
MAX_REQUEST_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 0.25
MAX_RETRY_AFTER_SECONDS = 5.0
_PEXELS_IMAGE_HOSTS = frozenset({"images.pexels.com"})
_PEXELS_PAGE_HOSTS = frozenset({"pexels.com", "www.pexels.com"})


class PexelsImageProvider:
    """Resolve attraction images through Pexels search with attribution."""

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not api_key.strip():
            raise ValueError("A Pexels API key is required")
        self._api_key = api_key.strip()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=3.0, read=7.0),
        )
        self._sleep = sleep

    async def resolve_image(self, *, place: ResolvedPlace) -> PlaceImage | None:
        query = build_pexels_query(place)
        logger.info(
            "image_resolution_started provider=pexels provider_place_id=%s query=%s",
            place.provider_place_id,
            query,
        )
        payload = await self._search(query)
        photos = payload.get("photos")
        if not isinstance(photos, list):
            raise ImageProviderError("Pexels returned an invalid search response")
        for photo in photos:
            image = parse_pexels_photo(photo)
            if image is not None:
                logger.info(
                    "image_resolution_resolved provider=pexels "
                    "provider_place_id=%s provider_image_id=%s",
                    place.provider_place_id,
                    image.provider_image_id,
                )
                return image
        logger.info(
            "image_resolution_unresolved provider=pexels provider_place_id=%s",
            place.provider_place_id,
        )
        return None

    async def _search(self, query: str) -> Mapping[str, Any]:
        for attempt in range(MAX_REQUEST_ATTEMPTS):
            try:
                response = await self._client.get(
                    PEXELS_SEARCH_URL,
                    headers={
                        "Authorization": self._api_key,
                        "Accept": "application/json",
                    },
                    params={
                        "query": query,
                        "per_page": PEXELS_RESULT_LIMIT,
                        "page": 1,
                        "locale": "en-US",
                    },
                )
            except httpx.HTTPError as exc:
                if attempt + 1 < MAX_REQUEST_ATTEMPTS:
                    await self._sleep(_retry_delay(None, attempt))
                    continue
                raise ImageProviderUnavailableError(
                    "Pexels request failed"
                ) from exc

            if response.status_code in {401, 403}:
                raise PexelsAccessError("Pexels rejected the configured API key")
            if response.status_code == 429:
                if attempt + 1 < MAX_REQUEST_ATTEMPTS:
                    await self._sleep(_retry_delay(response, attempt))
                    continue
                raise PexelsRateLimitError("Pexels API rate limit exceeded")
            if response.status_code >= 500:
                if attempt + 1 < MAX_REQUEST_ATTEMPTS:
                    await self._sleep(_retry_delay(response, attempt))
                    continue
                raise ImageProviderUnavailableError(
                    "Pexels is temporarily unavailable"
                )
            if response.status_code >= 400:
                raise ImageProviderError("Pexels rejected the image search")
            try:
                payload = response.json()
            except ValueError as exc:
                raise ImageProviderError("Pexels returned invalid JSON") from exc
            if not isinstance(payload, Mapping):
                raise ImageProviderError("Pexels returned an invalid response")
            return payload

        raise ImageProviderUnavailableError("Pexels request failed")

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def build_pexels_query(place: ResolvedPlace) -> str:
    """Build a focused search query from trusted place metadata."""

    parts = [place.name, place.city, place.country]
    return ", ".join(dict.fromkeys(part.strip() for part in parts if part and part.strip()))


def parse_pexels_photo(value: object) -> PlaceImage | None:
    """Convert one safe Pexels photo result into provider-neutral metadata."""

    if not isinstance(value, Mapping):
        return None
    photo_id = _identifier(value.get("id"))
    photographer = _text(value.get("photographer"))
    source_page_url = _trusted_url(value.get("url"), _PEXELS_PAGE_HOSTS)
    author_url = _trusted_url(value.get("photographer_url"), _PEXELS_PAGE_HOSTS)
    sources = value.get("src")
    if not isinstance(sources, Mapping):
        return None
    original_url = _trusted_url(sources.get("original"), _PEXELS_IMAGE_HOSTS)
    thumbnail_url = next(
        (
            trusted
            for candidate in (
                sources.get("large2x"),
                sources.get("large"),
                sources.get("landscape"),
                sources.get("medium"),
            )
            if (trusted := _trusted_url(candidate, _PEXELS_IMAGE_HOSTS)) is not None
        ),
        None,
    )
    if not all(
        (photo_id, photographer, source_page_url, author_url, original_url)
    ):
        return None
    try:
        return PlaceImage(
            provider="pexels",
            provider_image_id=photo_id,
            original_url=original_url,
            thumbnail_url=thumbnail_url,
            source_page_url=source_page_url,
            width=_positive_int(value.get("width")),
            height=_positive_int(value.get("height")),
            author=photographer,
            author_url=author_url,
            credit="Pexels",
            license_short_name="Pexels License",
            license_url=PEXELS_LICENSE_URL,
            usage_terms="Photo provided by Pexels; follow the Pexels API guidelines.",
            attribution_text=f"Photo by {photographer} on Pexels",
            description=_text(value.get("alt")),
        )
    except (ValidationError, ValueError):
        return None


def _trusted_url(value: object, hosts: frozenset[str]) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    parsed = urlsplit(normalized)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in hosts
        or parsed.username
        or parsed.password
    ):
        return None
    return normalized


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized or None


def _identifier(value: object) -> str | None:
    if isinstance(value, int) and value >= 0:
        return str(value)
    return _text(value)


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(MAX_RETRY_AFTER_SECONDS, max(0.0, float(retry_after)))
            except ValueError:
                pass
    return RETRY_BASE_DELAY_SECONDS * (2**attempt)
