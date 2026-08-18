import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
import logging
from typing import Any
from urllib.parse import quote_plus

import httpx

from app.core.logging import get_logger
from app.models import ResolvedPlace
from app.services.places.base import (
    PlaceResolution,
    build_place_query,
    normalize_place_text,
)

logger = get_logger(__name__)

GEOAPIFY_SEARCH_URL = "https://api.geoapify.com/v1/geocode/search"
GEOAPIFY_RESULT_LIMIT = 5
MAX_REQUEST_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 0.2
STRONG_MATCH_SCORE = 0.78
MINIMUM_MATCH_SCORE = 0.58
STRONG_CONFIDENCE_THRESHOLD = 0.85
MINIMUM_CONFIDENCE_THRESHOLD = 0.35


class GeoapifyProviderError(RuntimeError):
    """A safe provider error that never includes credentials or raw payloads."""


class GeoapifyAuthenticationError(GeoapifyProviderError):
    """Geoapify rejected the configured API credential."""


class GeoapifyRateLimitError(GeoapifyProviderError):
    """Geoapify rate limiting persisted after conservative retries."""


@dataclass(frozen=True)
class _ScoredCandidate:
    properties: Mapping[str, Any]
    score: float
    name_similarity: float
    city_match: bool
    destination_match: bool
    confidence: float | None


class _CredentialRedactionFilter(logging.Filter):
    """Redact the query-string credential from HTTP client request logs."""

    def __init__(self, secret: str) -> None:
        super().__init__()
        self._values = (secret, quote_plus(secret))

    def filter(self, record: logging.LogRecord) -> bool:
        if not isinstance(record.args, tuple):
            return True
        redacted_args = []
        for value in record.args:
            rendered = str(value)
            if any(secret in rendered for secret in self._values):
                for secret in self._values:
                    rendered = rendered.replace(secret, "[redacted]")
                redacted_args.append(rendered)
            else:
                redacted_args.append(value)
        record.args = tuple(redacted_args)
        return True


class GeoapifyPlacesProvider:
    """Resolve named itinerary activities through Geoapify forward geocoding."""

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Geoapify API key is required")
        self._api_key = api_key
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=3.0, read=7.0),
        )
        self._sleep = sleep

    async def resolve_place(
        self,
        *,
        name: str,
        location_hint: str | None,
        city: str | None,
        destination: str,
    ) -> PlaceResolution:
        query = build_place_query(
            name=name,
            location_hint=location_hint,
            city=city,
            destination=destination,
        )
        logger.info(
            "place_resolution_started activity=%s city=%s destination=%s",
            name,
            city,
            destination,
        )
        candidates = await self._search(query)
        resolution = select_geoapify_candidate(
            candidates,
            name=name,
            city=city,
            destination=destination,
        )
        logger.info(
            "place_resolution_%s activity=%s city=%s destination=%s candidates=%s",
            _status_log_suffix(resolution.status),
            name,
            city,
            destination,
            len(candidates),
        )
        return resolution

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _search(self, query: str) -> list[Mapping[str, Any]]:
        params = {
            "text": query,
            "format": "json",
            "lang": "en",
            "limit": GEOAPIFY_RESULT_LIMIT,
            "apiKey": self._api_key,
        }
        for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
            try:
                httpx_logger = logging.getLogger("httpx")
                redaction_filter = _CredentialRedactionFilter(self._api_key)
                httpx_logger.addFilter(redaction_filter)
                try:
                    response = await self._client.get(
                        GEOAPIFY_SEARCH_URL,
                        params=params,
                    )
                finally:
                    httpx_logger.removeFilter(redaction_filter)
            except httpx.TransportError as exc:
                if attempt < MAX_REQUEST_ATTEMPTS:
                    await self._backoff(attempt)
                    continue
                raise GeoapifyProviderError("Geoapify request failed") from exc

            if response.status_code in {401, 403}:
                raise GeoapifyAuthenticationError(
                    "Geoapify rejected the configured credential"
                )
            if response.status_code == 429:
                if attempt < MAX_REQUEST_ATTEMPTS:
                    await self._backoff(attempt)
                    continue
                raise GeoapifyRateLimitError("Geoapify rate limit exceeded")
            if 500 <= response.status_code < 600:
                if attempt < MAX_REQUEST_ATTEMPTS:
                    await self._backoff(attempt)
                    continue
                raise GeoapifyProviderError("Geoapify service unavailable")
            if response.status_code >= 400:
                raise GeoapifyProviderError(
                    f"Geoapify request rejected with status {response.status_code}"
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise GeoapifyProviderError("Geoapify returned invalid JSON") from exc
            if not isinstance(payload, Mapping):
                raise GeoapifyProviderError("Geoapify returned an unexpected payload")
            results = payload.get("results")
            if not isinstance(results, list):
                raise GeoapifyProviderError("Geoapify response omitted results")
            return [item for item in results if isinstance(item, Mapping)]

        return []

    async def _backoff(self, attempt: int) -> None:
        await self._sleep(RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)))


def select_geoapify_candidate(
    candidates: Sequence[Mapping[str, Any]],
    *,
    name: str,
    city: str | None,
    destination: str,
) -> PlaceResolution:
    """Select and classify the strongest usable candidate deterministically."""

    properties = [_candidate_properties(candidate) for candidate in candidates]
    usable = [candidate for candidate in properties if _has_place_identity(candidate)]
    if not usable:
        return PlaceResolution.unresolved()

    normalized_destination = normalize_place_text(destination)
    destination_is_country = any(
        normalize_place_text(_string(candidate.get("country")))
        == normalized_destination
        for candidate in usable
    )

    scored: list[_ScoredCandidate] = []
    for candidate in usable:
        scored_candidate = _score_candidate(
            candidate,
            name=name,
            city=city,
            destination=destination,
            destination_is_country=destination_is_country,
        )
        if scored_candidate is not None:
            scored.append(scored_candidate)
    if not scored:
        return PlaceResolution.unresolved()

    strongest = max(
        scored,
        key=lambda item: (
            item.score,
            item.confidence if item.confidence is not None else -1.0,
            normalize_place_text(_candidate_name(item.properties)),
        ),
    )
    has_location_support = strongest.city_match or strongest.destination_match
    if (
        strongest.score >= STRONG_MATCH_SCORE
        and strongest.name_similarity >= 0.75
        and has_location_support
    ):
        status = "resolved"
    elif (
        strongest.score >= MINIMUM_MATCH_SCORE
        and strongest.name_similarity >= 0.45
        and (
            has_location_support
            or (strongest.confidence or 0) >= STRONG_CONFIDENCE_THRESHOLD
        )
    ):
        status = "partially_resolved"
    else:
        return PlaceResolution.unresolved()

    place = _to_resolved_place(strongest.properties, status=status)
    return PlaceResolution(status=status, place=place)


def _score_candidate(
    candidate: Mapping[str, Any],
    *,
    name: str,
    city: str | None,
    destination: str,
    destination_is_country: bool,
) -> _ScoredCandidate | None:
    candidate_country = normalize_place_text(_string(candidate.get("country")))
    expected_destination = normalize_place_text(destination)
    destination_match, _ = _location_match(destination, candidate)
    if (
        destination_is_country
        and candidate_country
        and candidate_country != expected_destination
    ):
        return None
    if candidate_country and not destination_match:
        return None

    name_similarity = _text_similarity(name, _candidate_name(candidate))
    if name_similarity < 0.30:
        return None

    city_match, city_mismatch = _location_match(city, candidate)
    confidence = _confidence(candidate)
    result_type = normalize_place_text(_string(candidate.get("result_type")))
    type_score = 1.0 if result_type in {"amenity", "building"} else 0.4
    if result_type in {"street", "postcode", "country"}:
        type_score = 0.0

    score = (
        0.55 * name_similarity
        + 0.15 * float(city_match)
        + 0.15 * float(destination_match)
        + 0.05 * type_score
        + 0.10 * (confidence or 0.0)
    )
    if city_mismatch:
        score -= 0.25
    if confidence is not None and confidence < MINIMUM_CONFIDENCE_THRESHOLD:
        score -= 0.05

    return _ScoredCandidate(
        properties=candidate,
        score=max(0.0, min(score, 1.0)),
        name_similarity=name_similarity,
        city_match=city_match,
        destination_match=destination_match,
        confidence=confidence,
    )


def _to_resolved_place(
    candidate: Mapping[str, Any],
    *,
    status: str,
) -> ResolvedPlace:
    categories = candidate.get("categories")
    if isinstance(categories, list):
        parsed_categories = [str(item) for item in categories if str(item).strip()]
    else:
        category = _string(candidate.get("category"))
        parsed_categories = [category] if category else []

    datasource = candidate.get("datasource")
    attribution = None
    if isinstance(datasource, Mapping):
        attribution = _string(datasource.get("attribution"))
    attribution = attribution or _string(candidate.get("attribution"))

    return ResolvedPlace(
        provider="geoapify",
        provider_place_id=str(candidate["place_id"]),
        name=_candidate_name(candidate),
        formatted_address=_string(candidate.get("formatted")) or None,
        city=_string(candidate.get("city")) or None,
        state=_string(candidate.get("state")) or None,
        country=_string(candidate.get("country")) or None,
        country_code=_string(candidate.get("country_code")) or None,
        latitude=float(candidate["lat"]),
        longitude=float(candidate["lon"]),
        categories=parsed_categories,
        confidence=_confidence(candidate),
        resolution_status=status,
        source_attribution=attribution,
    )


def _candidate_properties(candidate: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = candidate.get("properties")
    return nested if isinstance(nested, Mapping) else candidate


def _has_place_identity(candidate: Mapping[str, Any]) -> bool:
    try:
        latitude = float(candidate["lat"])
        longitude = float(candidate["lon"])
    except (KeyError, TypeError, ValueError):
        return False
    return bool(
        _string(candidate.get("place_id"))
        and _candidate_name(candidate)
        and -90 <= latitude <= 90
        and -180 <= longitude <= 180
    )


def _candidate_name(candidate: Mapping[str, Any]) -> str:
    return (
        _string(candidate.get("name"))
        or _string(candidate.get("address_line1"))
    )


def _confidence(candidate: Mapping[str, Any]) -> float | None:
    rank = candidate.get("rank")
    value = rank.get("confidence") if isinstance(rank, Mapping) else None
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    return confidence if 0 <= confidence <= 1 else None


def _location_match(
    expected: str | None,
    candidate: Mapping[str, Any],
) -> tuple[bool, bool]:
    normalized_expected = normalize_place_text(expected)
    if not normalized_expected:
        return False, False
    location_values = [
        _string(candidate.get(key))
        for key in ("city", "district", "county", "state", "country", "formatted")
    ]
    normalized_values = [normalize_place_text(value) for value in location_values if value]
    matched = any(
        normalized_expected == value
        or normalized_expected in value
        or value in normalized_expected
        for value in normalized_values
    )
    candidate_city = normalize_place_text(_string(candidate.get("city")))
    mismatch = bool(candidate_city and not matched)
    return matched, mismatch


def _text_similarity(left: str, right: str) -> float:
    normalized_left = normalize_place_text(left)
    normalized_right = normalize_place_text(right)
    if not normalized_left or not normalized_right:
        return 0.0
    if normalized_left == normalized_right:
        return 1.0
    if normalized_left in normalized_right or normalized_right in normalized_left:
        return 0.9
    left_tokens = set(normalized_left.split())
    right_tokens = set(normalized_right.split())
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _string(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _status_log_suffix(status: str) -> str:
    if status == "partially_resolved":
        return "partial"
    return status
