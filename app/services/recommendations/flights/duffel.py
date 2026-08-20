import asyncio
import re
import unicodedata
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

import httpx
from pydantic import ValidationError

from app.core.logging import get_logger
from app.models import FlightOption, FlightSearchRequest, FlightSegment, FlightSlice
from app.services.recommendations.base import (
    FlightProviderError,
    FlightProviderUnavailableError,
)

logger = get_logger(__name__)

DUFFEL_BASE_URL = "https://api.duffel.com"
DUFFEL_PLACES_PATH = "/places/suggestions"
DUFFEL_OFFER_REQUESTS_PATH = "/air/offer_requests"
DUFFEL_OFFERS_PATH = "/air/offers"
DUFFEL_VERSION = "v2"
DUFFEL_SUPPLIER_TIMEOUT_MS = 10_000
MAX_DUFFEL_OFFERS_TO_CONSIDER = 50
MAX_GET_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 0.2

_DURATION_PATTERN = re.compile(
    r"^P(?:(?P<days>\d+)D)?T(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$"
)


class DuffelAuthenticationError(FlightProviderUnavailableError):
    """Duffel rejected the configured access token."""


class DuffelRateLimitError(FlightProviderUnavailableError):
    """Duffel rate limiting persisted after bounded retries."""


class DuffelPlaceResolutionError(FlightProviderUnavailableError):
    """A flight endpoint could not be resolved without guessing."""


@dataclass(frozen=True)
class DuffelFlightPlace:
    """The minimal trusted Duffel place identity needed for flight search."""

    provider_place_id: str
    code: str
    name: str
    place_type: Literal["city", "airport"]
    country_code: str
    city_name: str | None = None


class DuffelFlightProvider:
    """Resolve endpoints and normalize bounded Duffel flight offer searches."""

    def __init__(
        self,
        access_token: str,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not access_token.strip():
            raise ValueError("Duffel access token is required")
        self._access_token = access_token.strip()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=DUFFEL_BASE_URL,
            timeout=httpx.Timeout(
                16.0,
                connect=3.0,
                read=15.0,
                write=5.0,
                pool=5.0,
            ),
        )
        self._sleep = sleep
        self._now = now

    async def resolve_place(
        self,
        query: str,
        *,
        country_hint: str | None = None,
    ) -> DuffelFlightPlace | None:
        payload = await self._get_json(
            DUFFEL_PLACES_PATH,
            params={"query": query},
        )
        candidates = payload.get("data")
        if not isinstance(candidates, list):
            raise FlightProviderError("Duffel Places response omitted data")
        place = select_duffel_place(
            [candidate for candidate in candidates if isinstance(candidate, Mapping)],
            query=query,
            country_hint=country_hint,
        )
        if place is None:
            logger.warning(
                "duffel_place_unresolved query=%s country_hint=%s",
                query,
                country_hint,
            )
        return place

    async def search_flights(
        self,
        request: FlightSearchRequest,
    ) -> list[FlightOption]:
        return_origin = request.return_origin or request.destination
        return_destination = request.return_destination or request.origin
        endpoint_inputs = [
            (request.origin, request.origin_country_hint),
            (request.destination, request.destination_country_hint),
        ]
        if request.return_date is not None:
            endpoint_inputs.extend(
                [
                    (return_origin, request.return_origin_country_hint),
                    (return_destination, request.return_destination_country_hint),
                ]
            )

        resolved_cache: dict[tuple[str, str], DuffelFlightPlace] = {}
        resolved_places: list[DuffelFlightPlace] = []
        for query, country_hint in endpoint_inputs:
            cache_key = (
                _normalize_text(query),
                _normalize_country_hint(country_hint) or "",
            )
            place = resolved_cache.get(cache_key)
            if place is None:
                place = await self.resolve_place(query, country_hint=country_hint)
                if place is None:
                    raise DuffelPlaceResolutionError(
                        f"Duffel could not resolve flight endpoint: {query}"
                    )
                resolved_cache[cache_key] = place
            resolved_places.append(place)

        slices = [
            {
                "origin": resolved_places[0].code,
                "destination": resolved_places[1].code,
                "departure_date": request.departure_date.isoformat(),
            }
        ]
        if request.return_date is not None:
            slices.append(
                {
                    "origin": resolved_places[2].code,
                    "destination": resolved_places[3].code,
                    "departure_date": request.return_date.isoformat(),
                }
            )

        offer_request_id, request_live_mode = await self._create_offer_request(
            slices=slices,
            adults=request.adults,
        )
        return await self._list_offers(
            offer_request_id,
            fallback_live_mode=request_live_mode,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _create_offer_request(
        self,
        *,
        slices: list[dict[str, str]],
        adults: int,
    ) -> tuple[str, bool | None]:
        payload = await self._post_json(
            DUFFEL_OFFER_REQUESTS_PATH,
            params={
                "return_offers": "false",
                "supplier_timeout": DUFFEL_SUPPLIER_TIMEOUT_MS,
            },
            json={
                "data": {
                    "slices": slices,
                    "passengers": [{"type": "adult"} for _ in range(adults)],
                    "cabin_class": "economy",
                }
            },
        )
        data = payload.get("data")
        if not isinstance(data, Mapping) or not _clean_string(data.get("id")):
            raise FlightProviderError("Duffel Offer Request response omitted its ID")
        live_mode = data.get("live_mode")
        if not isinstance(live_mode, bool):
            live_mode = not self._access_token.startswith("duffel_test_")
        return str(data["id"]), live_mode

    async def _list_offers(
        self,
        offer_request_id: str,
        *,
        fallback_live_mode: bool | None,
    ) -> list[FlightOption]:
        payload = await self._get_json(
            DUFFEL_OFFERS_PATH,
            params={
                "offer_request_id": offer_request_id,
                "sort": "total_amount",
                "limit": MAX_DUFFEL_OFFERS_TO_CONSIDER,
            },
        )
        data = payload.get("data")
        if not isinstance(data, list):
            raise FlightProviderError("Duffel Offers response omitted data")

        fetched_at = self._now()
        options: list[FlightOption] = []
        for raw_offer in data:
            if not isinstance(raw_offer, Mapping):
                continue
            try:
                options.append(
                    parse_duffel_offer(
                        raw_offer,
                        fetched_at=fetched_at,
                        fallback_live_mode=fallback_live_mode,
                    )
                )
            except (FlightProviderError, ValidationError, ValueError, TypeError):
                logger.warning(
                    "duffel_offer_skipped offer_id=%s reason=malformed",
                    _clean_string(raw_offer.get("id")) or "unknown",
                )

        if data and not options:
            raise FlightProviderError("Duffel returned no valid flight offers")
        logger.info(
            "duffel_offers_received offer_request_id=%s count=%s",
            offer_request_id,
            len(options),
        )
        return options

    async def _get_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        for attempt in range(1, MAX_GET_ATTEMPTS + 1):
            try:
                response = await self._client.get(
                    path,
                    params=params,
                    headers=self._headers(),
                )
            except httpx.TransportError as exc:
                if attempt < MAX_GET_ATTEMPTS:
                    await self._backoff(attempt)
                    continue
                raise FlightProviderUnavailableError("Duffel GET request failed") from exc

            if response.status_code == 429 or 500 <= response.status_code < 600:
                if attempt < MAX_GET_ATTEMPTS:
                    await self._backoff(attempt)
                    continue
            self._raise_for_status(response)
            return _decode_payload(response)

        raise FlightProviderUnavailableError("Duffel GET request failed")

    async def _post_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any],
        json: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        try:
            response = await self._client.post(
                path,
                params=params,
                json=json,
                headers=self._headers(content_type=True),
            )
        except httpx.TransportError as exc:
            # Do not retry an ambiguous Offer Request creation.
            raise FlightProviderUnavailableError("Duffel POST request failed") from exc
        self._raise_for_status(response)
        return _decode_payload(response)

    def _headers(self, *, content_type: bool = False) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Duffel-Version": DUFFEL_VERSION,
            "Accept": "application/json",
        }
        if content_type:
            headers["Content-Type"] = "application/json"
        return headers

    def _raise_for_status(self, response: httpx.Response) -> None:
        request_id = response.headers.get("x-request-id")
        if response.status_code < 400:
            return
        logger.warning(
            "duffel_request_failed status=%s x_request_id=%s",
            response.status_code,
            request_id or "unavailable",
        )
        if response.status_code in {401, 403}:
            raise DuffelAuthenticationError("Duffel rejected the configured token")
        if response.status_code == 429:
            raise DuffelRateLimitError("Duffel rate limit exceeded")
        if 500 <= response.status_code < 600:
            raise FlightProviderUnavailableError("Duffel service unavailable")
        raise FlightProviderError(
            f"Duffel request rejected with status {response.status_code}"
        )

    async def _backoff(self, attempt: int) -> None:
        await self._sleep(RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)))


def select_duffel_place(
    candidates: Sequence[Mapping[str, Any]],
    *,
    query: str,
    country_hint: str | None = None,
) -> DuffelFlightPlace | None:
    """Select a trustworthy Duffel city or airport without inventing an IATA code."""

    places = [place for candidate in candidates if (place := _parse_place(candidate))]
    if not places:
        return None

    normalized_country = _normalize_country_hint(country_hint)
    if normalized_country:
        country_matches = [
            place for place in places if place.country_code == normalized_country
        ]
        if not country_matches:
            return None
        places = country_matches

    normalized_query = _normalize_text(query)
    code_matches = [place for place in places if place.code.casefold() == normalized_query]
    if code_matches:
        return _prefer_city(code_matches)

    exact_matches = [
        place
        for place in places
        if normalized_query
        in {
            _normalize_text(place.name),
            _normalize_text(place.city_name),
        }
    ]
    if exact_matches:
        exact_cities = [
            place
            for place in exact_matches
            if place.place_type == "city" and _normalize_text(place.name) == normalized_query
        ]
        preferred_matches = exact_cities or exact_matches
        identities = {
            (place.country_code, place.code) for place in preferred_matches
        }
        if len(identities) > 1 and normalized_country is None:
            return None
        return _prefer_city(preferred_matches)

    cities = [place for place in places if place.place_type == "city"]
    if cities:
        return cities[0]
    airports = [place for place in places if place.place_type == "airport"]
    return airports[0] if airports else None


def parse_duffel_offer(
    raw_offer: Mapping[str, Any],
    *,
    fetched_at: datetime,
    fallback_live_mode: bool | None = None,
) -> FlightOption:
    """Normalize one Duffel offer while retaining required operating carriers."""

    offer_id = _required_string(raw_offer, "id", "offer ID")
    total_amount = _parse_amount(raw_offer.get("total_amount"))
    currency = _required_string(raw_offer, "total_currency", "currency")
    raw_slices = raw_offer.get("slices")
    if not isinstance(raw_slices, list) or not raw_slices:
        raise FlightProviderError("Duffel offer omitted slices")
    slices = [_parse_slice(raw_slice) for raw_slice in raw_slices]

    owner = raw_offer.get("owner")
    owner_mapping = owner if isinstance(owner, Mapping) else {}
    airline_name = _clean_string(owner_mapping.get("name"))
    airline_code = _clean_string(owner_mapping.get("iata_code"))
    if airline_name is None:
        airline_name = slices[0].segments[0].operating_carrier_name

    live_mode = raw_offer.get("live_mode")
    if not isinstance(live_mode, bool):
        live_mode = fallback_live_mode

    return FlightOption(
        provider="duffel",
        provider_offer_id=offer_id,
        origin_code=slices[0].origin_code,
        destination_code=slices[0].destination_code,
        departure_at=slices[0].segments[0].departure_at,
        arrival_at=slices[-1].segments[-1].arrival_at,
        total_duration_minutes=sum(item.duration_minutes for item in slices),
        stops=sum(item.stops for item in slices),
        total_price=float(total_amount),
        currency=currency,
        airline_name=airline_name,
        airline_code=airline_code,
        slices=slices,
        expires_at=_optional_datetime(raw_offer.get("expires_at")),
        live_data=live_mode,
        external_url=None,
        fetched_at=fetched_at,
    )


def _parse_slice(raw_slice: Any) -> FlightSlice:
    if not isinstance(raw_slice, Mapping):
        raise FlightProviderError("Duffel offer contained an invalid slice")
    raw_segments = raw_slice.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise FlightProviderError("Duffel slice omitted segments")
    segments = [_parse_segment(raw_segment) for raw_segment in raw_segments]
    origin_code = _place_code(raw_slice.get("origin")) or segments[0].origin_code
    destination_code = (
        _place_code(raw_slice.get("destination")) or segments[-1].destination_code
    )
    duration_minutes = _duration_minutes(raw_slice.get("duration"))
    return FlightSlice(
        origin_code=origin_code,
        destination_code=destination_code,
        duration_minutes=duration_minutes,
        stops=len(segments) - 1,
        segments=segments,
    )


def _parse_segment(raw_segment: Any) -> FlightSegment:
    if not isinstance(raw_segment, Mapping):
        raise FlightProviderError("Duffel slice contained an invalid segment")
    carrier = raw_segment.get("operating_carrier")
    if not isinstance(carrier, Mapping):
        raise FlightProviderError("Duffel segment omitted its operating carrier")
    flight_number = _clean_string(
        raw_segment.get("operating_carrier_flight_number")
    ) or _clean_string(raw_segment.get("marketing_carrier_flight_number"))
    return FlightSegment(
        origin_code=_required_place_code(raw_segment.get("origin"), "segment origin"),
        destination_code=_required_place_code(
            raw_segment.get("destination"),
            "segment destination",
        ),
        departure_at=_required_datetime(raw_segment.get("departing_at"), "departure"),
        arrival_at=_required_datetime(raw_segment.get("arriving_at"), "arrival"),
        operating_carrier_name=_required_string(
            carrier,
            "name",
            "operating carrier name",
        ),
        operating_carrier_code=_clean_string(carrier.get("iata_code")),
        flight_number=flight_number,
    )


def _parse_place(candidate: Mapping[str, Any]) -> DuffelFlightPlace | None:
    place_type = _clean_string(candidate.get("type"))
    code = _clean_string(candidate.get("iata_code"))
    name = _clean_string(candidate.get("name"))
    country_code = _clean_string(candidate.get("iata_country_code"))
    provider_place_id = _clean_string(candidate.get("id"))
    if (
        place_type not in {"city", "airport"}
        or not code
        or len(code) != 3
        or not name
        or not country_code
        or len(country_code) != 2
        or not provider_place_id
    ):
        return None
    return DuffelFlightPlace(
        provider_place_id=provider_place_id,
        code=code.upper(),
        name=name,
        place_type=place_type,
        country_code=country_code.upper(),
        city_name=_clean_string(candidate.get("city_name")),
    )


def _prefer_city(places: Sequence[DuffelFlightPlace]) -> DuffelFlightPlace:
    return next(
        (place for place in places if place.place_type == "city"),
        places[0],
    )


def _decode_payload(response: httpx.Response) -> Mapping[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise FlightProviderError("Duffel returned invalid JSON") from exc
    if not isinstance(payload, Mapping):
        raise FlightProviderError("Duffel returned an unexpected payload")
    return payload


def _parse_amount(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise FlightProviderError("Duffel offer contained an invalid total") from exc
    if not amount.is_finite() or amount < 0:
        raise FlightProviderError("Duffel offer contained an invalid total")
    return amount


def _duration_minutes(value: Any) -> int:
    if not isinstance(value, str):
        raise FlightProviderError("Duffel slice omitted its duration")
    match = _DURATION_PATTERN.fullmatch(value)
    if match is None:
        raise FlightProviderError("Duffel slice contained an invalid duration")
    values = {key: int(raw or 0) for key, raw in match.groupdict().items()}
    seconds = (
        values["days"] * 86_400
        + values["hours"] * 3_600
        + values["minutes"] * 60
        + values["seconds"]
    )
    if seconds <= 0:
        raise FlightProviderError("Duffel slice contained an invalid duration")
    return max(1, (seconds + 59) // 60)


def _required_datetime(value: Any, label: str) -> datetime:
    parsed = _optional_datetime(value)
    if parsed is None:
        raise FlightProviderError(f"Duffel offer omitted {label}")
    return parsed


def _optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise FlightProviderError("Duffel offer contained an invalid datetime")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FlightProviderError("Duffel offer contained an invalid datetime") from exc


def _required_place_code(value: Any, label: str) -> str:
    code = _place_code(value)
    if code is None:
        raise FlightProviderError(f"Duffel offer omitted {label}")
    return code


def _place_code(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    code = _clean_string(value.get("iata_code"))
    return code.upper() if code and len(code) == 3 else None


def _required_string(
    mapping: Mapping[str, Any],
    key: str,
    label: str,
) -> str:
    value = _clean_string(mapping.get(key))
    if value is None:
        raise FlightProviderError(f"Duffel offer omitted {label}")
    return value


def _clean_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_text.casefold()).split())


def _normalize_country_hint(value: str | None) -> str | None:
    normalized = _normalize_text(value).replace(" ", "")
    return normalized.upper() if len(normalized) == 2 and normalized.isalpha() else None
