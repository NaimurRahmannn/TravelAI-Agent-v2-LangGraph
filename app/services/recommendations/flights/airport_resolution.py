import asyncio
import logging
import math
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote_plus

import httpx

from app.core.logging import get_logger
from app.services.recommendations.base import FlightProviderUnavailableError

logger = get_logger(__name__)

GEOAPIFY_GEOCODE_URL = "https://api.geoapify.com/v1/geocode/search"
GEOAPIFY_PLACES_URL = "https://api.geoapify.com/v2/places"
GEOAPIFY_PLACE_DETAILS_URL = "https://api.geoapify.com/v2/place-details"
AIRPORT_CATEGORIES = "airport.international,airport"
AIRPORT_SEARCH_RADIUS_METERS = 100_000
MAX_CITY_RESULTS = 5
MAX_AIRPORT_CANDIDATES = 6
MAX_REQUEST_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 0.2


class AirportResolutionError(FlightProviderUnavailableError):
    """A flight endpoint could not be resolved to a trusted airport IATA code."""


class AirportResolver(Protocol):
    async def resolve_airport(
        self,
        query: str,
        *,
        country_hint: str | None = None,
    ) -> str:
        """Resolve an endpoint to a provider-backed three-letter IATA code."""


@dataclass(frozen=True)
class AirportCandidate:
    iata: str
    country_code: str | None
    categories: tuple[str, ...]
    city: str | None
    closest_town: str | None
    distance_meters: float


class _CredentialRedactionFilter(logging.Filter):
    def __init__(self, secret: str) -> None:
        super().__init__()
        self._values = (secret, quote_plus(secret))

    def filter(self, record: logging.LogRecord) -> bool:
        if not isinstance(record.args, tuple):
            return True
        redacted: list[object] = []
        for value in record.args:
            rendered = str(value)
            if any(secret in rendered for secret in self._values):
                for secret in self._values:
                    rendered = rendered.replace(secret, "[redacted]")
                redacted.append(rendered)
            else:
                redacted.append(value)
        record.args = tuple(redacted)
        return True


class GeoapifyAirportResolver:
    """Resolve trip endpoints using Geoapify city, airport, and details facts."""

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Geoapify API key is required")
        self._api_key = api_key.strip()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(12.0, connect=3.0, read=9.0),
        )
        self._sleep = sleep
        self._cache: dict[tuple[str, str], str] = {}

    async def resolve_airport(
        self,
        query: str,
        *,
        country_hint: str | None = None,
    ) -> str:
        direct_code = normalize_iata(query)
        if direct_code is not None:
            return direct_code

        normalized_country = normalize_country_code(country_hint)
        cache_key = (normalize_text(query), normalized_country or "")
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        city = await self._resolve_city(query, normalized_country)
        candidates = await self._resolve_airport_candidates(city)
        selected = select_airport_candidate(
            candidates,
            requested_city=query,
            country_code=city.country_code,
        )
        if selected is None:
            raise AirportResolutionError(
                f"No trusted airport IATA code was found for {query.strip()}"
            )
        self._cache[cache_key] = selected.iata
        return selected.iata

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _resolve_city(
        self,
        query: str,
        country_hint: str | None,
    ) -> "_ResolvedCity":
        params: dict[str, Any] = {
            "text": query,
            "type": "city",
            "format": "json",
            "lang": "en",
            "limit": MAX_CITY_RESULTS,
            "apiKey": self._api_key,
        }
        if country_hint:
            params["filter"] = f"countrycode:{country_hint.casefold()}"
        payload = await self._get_json(GEOAPIFY_GEOCODE_URL, params=params)
        results = payload.get("results") if isinstance(payload, Mapping) else None
        if not isinstance(results, list):
            raise AirportResolutionError("Geoapify city response omitted results")
        city = select_city_candidate(
            [item for item in results if isinstance(item, Mapping)],
            query=query,
            country_hint=country_hint,
        )
        if city is None:
            raise AirportResolutionError(
                f"Geoapify could not resolve the flight endpoint {query.strip()}"
            )
        return city

    async def _resolve_airport_candidates(
        self,
        city: "_ResolvedCity",
    ) -> list[AirportCandidate]:
        proximity = f"{city.longitude},{city.latitude}"
        payload = await self._get_json(
            GEOAPIFY_PLACES_URL,
            params={
                "categories": AIRPORT_CATEGORIES,
                "filter": (
                    f"circle:{proximity},{AIRPORT_SEARCH_RADIUS_METERS}"
                ),
                "bias": f"proximity:{proximity}",
                "limit": MAX_AIRPORT_CANDIDATES,
                "lang": "en",
                "apiKey": self._api_key,
            },
        )
        features = payload.get("features") if isinstance(payload, Mapping) else None
        if not isinstance(features, list):
            raise AirportResolutionError("Geoapify airport response omitted features")

        candidates: list[AirportCandidate] = []
        for feature in features[:MAX_AIRPORT_CANDIDATES]:
            properties = _feature_properties(feature)
            place_id = clean_string(properties.get("place_id"))
            if place_id is None:
                continue
            details = await self._get_json(
                GEOAPIFY_PLACE_DETAILS_URL,
                params={
                    "id": place_id,
                    "features": "details",
                    "lang": "en",
                    "apiKey": self._api_key,
                },
            )
            detail_properties = _first_detail_properties(details)
            candidate = build_airport_candidate(properties, detail_properties, city)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    async def _get_json(
        self,
        url: str,
        *,
        params: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
            try:
                httpx_logger = logging.getLogger("httpx")
                redaction_filter = _CredentialRedactionFilter(self._api_key)
                httpx_logger.addFilter(redaction_filter)
                try:
                    response = await self._client.get(url, params=params)
                finally:
                    httpx_logger.removeFilter(redaction_filter)
            except httpx.TransportError as exc:
                if attempt < MAX_REQUEST_ATTEMPTS:
                    await self._sleep(RETRY_DELAY_SECONDS * attempt)
                    continue
                raise AirportResolutionError("Geoapify airport request failed") from exc

            if response.status_code in {401, 403}:
                raise AirportResolutionError(
                    "Geoapify rejected the configured credential"
                )
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < MAX_REQUEST_ATTEMPTS:
                    await self._sleep(RETRY_DELAY_SECONDS * attempt)
                    continue
                raise AirportResolutionError(
                    "Geoapify airport resolution is temporarily unavailable"
                )
            if response.status_code >= 400:
                raise AirportResolutionError(
                    f"Geoapify airport request failed with status {response.status_code}"
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise AirportResolutionError(
                    "Geoapify airport response contained invalid JSON"
                ) from exc
            if not isinstance(payload, Mapping):
                raise AirportResolutionError(
                    "Geoapify airport response had an unexpected shape"
                )
            return payload
        raise AirportResolutionError("Geoapify airport request failed")


@dataclass(frozen=True)
class _ResolvedCity:
    latitude: float
    longitude: float
    country_code: str


def select_city_candidate(
    candidates: Sequence[Mapping[str, Any]],
    *,
    query: str,
    country_hint: str | None,
) -> _ResolvedCity | None:
    expected_country = normalize_country_code(country_hint)
    requested_city = normalize_text(query)
    scored: list[tuple[int, float, str, _ResolvedCity]] = []
    for candidate in candidates:
        country = normalize_country_code(clean_string(candidate.get("country_code")))
        if country is None or (expected_country and country != expected_country):
            continue
        latitude = finite_float(candidate.get("lat"))
        longitude = finite_float(candidate.get("lon"))
        if latitude is None or longitude is None:
            continue
        names = {
            normalize_text(clean_string(candidate.get(field)) or "")
            for field in ("city", "name")
        }
        exact_match = int(requested_city in names)
        confidence = finite_float(candidate.get("rank", {}).get("confidence")) if isinstance(candidate.get("rank"), Mapping) else None
        place_id = clean_string(candidate.get("place_id")) or ""
        scored.append(
            (
                exact_match,
                confidence or 0.0,
                place_id,
                _ResolvedCity(latitude, longitude, country),
            )
        )
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return scored[0][3]


def build_airport_candidate(
    place: Mapping[str, Any],
    details: Mapping[str, Any],
    city: _ResolvedCity,
) -> AirportCandidate | None:
    airport = details.get("airport")
    if not isinstance(airport, Mapping):
        return None
    iata = normalize_iata(clean_string(airport.get("iata")) or "")
    if iata is None:
        return None
    country = normalize_country_code(
        clean_string(details.get("country_code"))
        or clean_string(place.get("country_code"))
    )
    categories_value = place.get("categories")
    categories = tuple(
        sorted(
            str(value).strip()
            for value in categories_value
            if isinstance(value, str) and value.strip()
        )
    ) if isinstance(categories_value, list) else ()
    distance = finite_float(place.get("distance"))
    if distance is None:
        distance = _distance_meters(
            city.latitude,
            city.longitude,
            finite_float(place.get("lat")),
            finite_float(place.get("lon")),
        )
    return AirportCandidate(
        iata=iata,
        country_code=country,
        categories=categories,
        city=clean_string(details.get("city")) or clean_string(place.get("city")),
        closest_town=clean_string(airport.get("closest_town")),
        distance_meters=distance if distance is not None else math.inf,
    )


def select_airport_candidate(
    candidates: Sequence[AirportCandidate],
    *,
    requested_city: str,
    country_code: str,
) -> AirportCandidate | None:
    matching_country = [
        candidate
        for candidate in candidates
        if candidate.country_code == country_code
    ]
    if not matching_country:
        return None
    normalized_city = normalize_text(requested_city)
    return min(
        matching_country,
        key=lambda candidate: (
            "airport.international" not in candidate.categories,
            normalized_city
            not in {
                normalize_text(candidate.city or ""),
                normalize_text(candidate.closest_town or ""),
            },
            candidate.distance_meters,
            candidate.iata,
        ),
    )


def normalize_iata(value: str) -> str | None:
    normalized = value.strip().upper()
    return normalized if re.fullmatch(r"[A-Z]{3}", normalized) else None


def normalize_country_code(value: str | None) -> str | None:
    normalized = value.strip().upper() if value else ""
    return normalized if re.fullmatch(r"[A-Z]{2}", normalized) else None


def normalize_text(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def clean_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _feature_properties(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    properties = value.get("properties")
    return properties if isinstance(properties, Mapping) else {}


def _first_detail_properties(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    features = payload.get("features")
    if not isinstance(features, list):
        return {}
    for feature in features:
        properties = _feature_properties(feature)
        if properties.get("feature_type") == "details":
            return properties
    return {}


def _distance_meters(
    origin_lat: float,
    origin_lon: float,
    candidate_lat: float | None,
    candidate_lon: float | None,
) -> float | None:
    if candidate_lat is None or candidate_lon is None:
        return None
    lat1 = math.radians(origin_lat)
    lat2 = math.radians(candidate_lat)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(candidate_lon - origin_lon)
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * 6_371_000 * math.asin(math.sqrt(haversine))
