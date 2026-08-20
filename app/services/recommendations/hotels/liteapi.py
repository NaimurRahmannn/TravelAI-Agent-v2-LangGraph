import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.models import HotelOption, HotelSearchRequest
from app.services.recommendations.base import HotelProviderUnavailableError

LITEAPI_RATES_URL = "https://api.liteapi.travel/v3.0/hotels/rates"
LITEAPI_TIMEOUT_SECONDS = 12
LITEAPI_MAX_RETRIES = 1
LITEAPI_RETRY_DELAY_SECONDS = 0.25
LITEAPI_RESULT_LIMIT = 20
LITEAPI_MAX_RATES_PER_HOTEL = 1
_MONEY_QUANTUM = Decimal("0.01")


class LiteApiAuthenticationError(HotelProviderUnavailableError):
    """LiteAPI rejected the configured credential."""


class LiteApiRateLimitError(HotelProviderUnavailableError):
    """LiteAPI rate limiting persisted after bounded retries."""


class LiteApiResponseError(HotelProviderUnavailableError):
    """LiteAPI returned an unusable response."""


class LiteApiHotelProvider:
    """Retrieve and normalize LiteAPI total-stay hotel rates."""

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not api_key.strip():
            raise ValueError("LiteAPI API key is required")
        self._api_key = api_key.strip()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(
                LITEAPI_TIMEOUT_SECONDS,
                connect=3.0,
                read=9.0,
            )
        )
        self._sleep = sleep
        self._now = now

    async def search_hotels(
        self,
        request: HotelSearchRequest,
    ) -> list[HotelOption]:
        payload = await self._post_rates(_build_rates_request(request))
        return parse_liteapi_hotels(
            payload,
            request=request,
            fetched_at=self._now(),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _post_rates(self, body: Mapping[str, Any]) -> Mapping[str, Any]:
        attempts = LITEAPI_MAX_RETRIES + 1
        for attempt in range(1, attempts + 1):
            try:
                response = await self._client.post(
                    LITEAPI_RATES_URL,
                    headers={
                        "X-API-Key": self._api_key,
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    json=dict(body),
                )
            except httpx.TransportError as exc:
                if attempt < attempts:
                    await self._backoff(attempt)
                    continue
                raise HotelProviderUnavailableError(
                    "LiteAPI hotel search failed"
                ) from exc

            if response.status_code in {401, 403}:
                raise LiteApiAuthenticationError(
                    "LiteAPI rejected the configured credential"
                )
            if response.status_code == 429:
                if attempt < attempts:
                    await self._backoff(attempt)
                    continue
                raise LiteApiRateLimitError("LiteAPI rate limit exceeded")
            if 500 <= response.status_code < 600:
                if attempt < attempts:
                    await self._backoff(attempt)
                    continue
                raise HotelProviderUnavailableError(
                    "LiteAPI hotel search is temporarily unavailable"
                )
            if response.status_code >= 400:
                raise LiteApiResponseError(
                    f"LiteAPI hotel search was rejected with status "
                    f"{response.status_code}"
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise LiteApiResponseError("LiteAPI returned invalid JSON") from exc
            if not isinstance(payload, Mapping):
                raise LiteApiResponseError(
                    "LiteAPI returned an unexpected response shape"
                )
            return payload

        raise HotelProviderUnavailableError("LiteAPI hotel search failed")

    async def _backoff(self, attempt: int) -> None:
        await self._sleep(LITEAPI_RETRY_DELAY_SECONDS * attempt)


def _build_rates_request(request: HotelSearchRequest) -> dict[str, Any]:
    return {
        "occupancies": [{"adults": request.adults}],
        "currency": "USD",
        "guestNationality": request.guest_nationality_country_code,
        "checkin": request.check_in.isoformat(),
        "checkout": request.check_out.isoformat(),
        "latitude": request.latitude,
        "longitude": request.longitude,
        "radius": request.radius_meters,
        "roomMapping": True,
        "maxRatesPerHotel": LITEAPI_MAX_RATES_PER_HOTEL,
        "includeHotelData": True,
        "limit": LITEAPI_RESULT_LIMIT,
    }


def parse_liteapi_hotels(
    payload: Mapping[str, Any],
    *,
    request: HotelSearchRequest,
    fetched_at: datetime,
) -> list[HotelOption]:
    data = payload.get("data")
    if not isinstance(data, list):
        raise LiteApiResponseError("LiteAPI response omitted hotel rate data")
    if not data:
        return []

    metadata = _hotel_metadata_by_id(payload.get("hotels"))
    is_sandbox = payload.get("sandbox") is True
    parsed: list[HotelOption] = []
    for hotel_value in data[:LITEAPI_RESULT_LIMIT]:
        if not isinstance(hotel_value, Mapping):
            continue
        hotel_id = _clean_string(hotel_value.get("hotelId"))
        if hotel_id is None:
            continue
        hotel_metadata = metadata.get(hotel_id, {})
        option = _parse_hotel_option(
            hotel_value,
            hotel_metadata,
            request=request,
            fetched_at=fetched_at,
            is_sandbox=is_sandbox,
        )
        if option is not None:
            parsed.append(option)

    if not parsed:
        raise LiteApiResponseError("LiteAPI returned no usable hotel rates")
    return parsed


def _parse_hotel_option(
    hotel: Mapping[str, Any],
    metadata: Mapping[str, Any],
    *,
    request: HotelSearchRequest,
    fetched_at: datetime,
    is_sandbox: bool,
) -> HotelOption | None:
    hotel_id = _clean_string(hotel.get("hotelId"))
    name = (
        _clean_string(metadata.get("name"))
        or _clean_string(hotel.get("hotelName"))
    )
    if hotel_id is None or name is None:
        return None

    rate_choice = _cheapest_rate(hotel.get("roomTypes"), currency="USD")
    if rate_choice is None:
        return None
    offer_id, rate, total = rate_choice
    nights = (request.check_out - request.check_in).days
    if nights <= 0:
        return None
    per_night = (total / Decimal(nights)).quantize(
        _MONEY_QUANTUM,
        rounding=ROUND_HALF_UP,
    )

    latitude, longitude = _coordinates(metadata)
    try:
        return HotelOption(
            provider="liteapi",
            provider_hotel_id=hotel_id,
            provider_offer_id=offer_id,
            name=name,
            # Keep the deterministic stay label even when provider metadata
            # names a neighborhood or municipality differently.
            city=request.city,
            country=_clean_string(metadata.get("country")),
            formatted_address=(
                _clean_string(metadata.get("address"))
                or _clean_string(metadata.get("formattedAddress"))
            ),
            latitude=latitude,
            longitude=longitude,
            check_in=request.check_in,
            check_out=request.check_out,
            nights=nights,
            total_price=float(total),
            currency="USD",
            price_per_night=float(per_night),
            room_name=_clean_string(rate.get("name")),
            board_name=_clean_string(rate.get("boardName")),
            rating=_nonnegative_float(metadata.get("rating")),
            review_count=_nonnegative_int(
                _first_present(
                    metadata.get("reviewCount"),
                    metadata.get("reviewsCount"),
                    metadata.get("review_count"),
                )
            ),
            refundable=_refundable(rate.get("cancellationPolicies")),
            taxes_included=_taxes_included(rate.get("retailRate")),
            image_url=_https_url(
                metadata.get("main_photo") or metadata.get("mainPhoto")
            ),
            external_url=None,
            is_sandbox=is_sandbox,
            fetched_at=fetched_at,
        )
    except ValueError:
        return None


def _cheapest_rate(
    room_types: Any,
    *,
    currency: str,
) -> tuple[str, Mapping[str, Any], Decimal] | None:
    if not isinstance(room_types, list):
        return None
    candidates: list[tuple[Decimal, str, Mapping[str, Any]]] = []
    for room in room_types:
        if not isinstance(room, Mapping):
            continue
        room_offer_id = _clean_string(room.get("offerId"))
        rates = room.get("rates")
        if not isinstance(rates, list):
            continue
        for rate in rates:
            if not isinstance(rate, Mapping):
                continue
            offer_id = _clean_string(rate.get("offerId")) or room_offer_id
            total = _retail_total(rate.get("retailRate"), currency=currency)
            if offer_id is not None and total is not None:
                candidates.append((total, offer_id, rate))
    if not candidates:
        return None
    total, offer_id, rate = min(candidates, key=lambda item: (item[0], item[1]))
    return offer_id, rate, total


def _retail_total(value: Any, *, currency: str) -> Decimal | None:
    if not isinstance(value, Mapping):
        return None
    totals = value.get("total")
    if not isinstance(totals, list):
        return None
    for total in totals:
        if not isinstance(total, Mapping):
            continue
        total_currency = _clean_string(total.get("currency"))
        if total_currency is None or total_currency.upper() != currency:
            continue
        amount = _decimal(total.get("amount"))
        if amount is not None and amount >= 0:
            return amount.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    return None


def _hotel_metadata_by_id(value: Any) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, list):
        return {}
    result: dict[str, Mapping[str, Any]] = {}
    for item in value:
        if not isinstance(item, Mapping):
            continue
        hotel_id = _clean_string(item.get("id")) or _clean_string(
            item.get("hotelId")
        )
        if hotel_id is not None:
            result[hotel_id] = item
    return result


def _coordinates(metadata: Mapping[str, Any]) -> tuple[float | None, float | None]:
    location = metadata.get("location")
    nested = location if isinstance(location, Mapping) else {}
    latitude = _finite_float(
        _first_present(metadata.get("latitude"), nested.get("latitude"))
    )
    longitude = _finite_float(
        _first_present(metadata.get("longitude"), nested.get("longitude"))
    )
    if latitude is None or longitude is None:
        return None, None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None, None
    return latitude, longitude


def _refundable(value: Any) -> bool | None:
    if not isinstance(value, Mapping):
        return None
    tag = _clean_string(value.get("refundableTag"))
    if tag is None:
        return None
    if tag.upper() == "RFN":
        return True
    if tag.upper() == "NRFN":
        return False
    return None


def _taxes_included(value: Any) -> bool | None:
    if not isinstance(value, Mapping) or "taxesAndFees" not in value:
        return None
    taxes = value.get("taxesAndFees")
    if taxes is None:
        return True
    if not isinstance(taxes, list) or not taxes:
        return None
    included: list[bool] = []
    for item in taxes:
        if not isinstance(item, Mapping) or not isinstance(
            item.get("included"), bool
        ):
            return None
        included.append(item["included"])
    if all(included):
        return True
    if not any(included):
        return False
    return None


def _https_url(value: Any) -> str | None:
    candidate = _clean_string(value)
    if candidate is None:
        return None
    parsed = urlsplit(candidate)
    return candidate if parsed.scheme == "https" and parsed.netloc else None


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def _finite_float(value: Any) -> float | None:
    result = _decimal(value)
    return float(result) if result is not None else None


def _nonnegative_float(value: Any) -> float | None:
    result = _finite_float(value)
    return result if result is not None and result >= 0 else None


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _clean_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _first_present(*values: Any) -> Any:
    return next((value for value in values if value is not None), None)
