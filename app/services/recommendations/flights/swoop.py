import asyncio
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from inspect import isawaitable
from typing import Any

from pydantic import ValidationError
from swoop import (
    SORT_CHEAPEST,
    Itinerary,
    Passengers,
    SearchLeg,
    SearchResult,
    Segment,
    SwoopError,
    SwoopHTTPError,
    SwoopParseError,
    SwoopRateLimitError,
    SwoopUpstreamError,
    TransportConfig,
    TripOption,
    search,
    search_legs,
)

from app.core.logging import get_logger
from app.models import (
    FlightLayover,
    FlightOption,
    FlightSearchRequest,
    FlightSegment,
    FlightSlice,
)
from app.services.recommendations.base import (
    FlightProviderError,
    FlightProviderUnavailableError,
)
from app.services.recommendations.flights.airport_resolution import AirportResolver

logger = get_logger(__name__)

SWOOP_POINT_OF_SALE_COUNTRY = "US"
SWOOP_TIMEOUT_SECONDS = 20
SWOOP_RETRIES = 1
MAX_SWOOP_RESULTS_TO_CONSIDER = 20
_MONEY_QUANTUM = Decimal("0.01")

SearchFunction = Callable[..., SearchResult]


class SwoopFlightProvider:
    """Normalize Swoop's Google Flights-derived shopping results."""

    def __init__(
        self,
        airport_resolver: AirportResolver,
        *,
        search_function: SearchFunction = search,
        search_legs_function: SearchFunction = search_legs,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._airport_resolver = airport_resolver
        self._search = search_function
        self._search_legs = search_legs_function
        self._now = now

    async def search_flights(
        self,
        request: FlightSearchRequest,
    ) -> list[FlightOption]:
        endpoints = await self._resolve_endpoints(request)
        passengers = Passengers(
            adults=request.adults,
            children=0,
            infants_in_seat=0,
            infants_on_lap=0,
        )
        transport = TransportConfig(
            timeout=SWOOP_TIMEOUT_SECONDS,
            retries=SWOOP_RETRIES,
            country=SWOOP_POINT_OF_SALE_COUNTRY,
        )

        try:
            if request.return_date is None:
                result = await asyncio.to_thread(
                    self._search,
                    endpoints[0],
                    endpoints[1],
                    request.departure_date.isoformat(),
                    cabin="economy",
                    passengers=passengers,
                    sort=SORT_CHEAPEST,
                    transport=transport,
                )
            elif endpoints[2] == endpoints[1] and endpoints[3] == endpoints[0]:
                result = await asyncio.to_thread(
                    self._search,
                    endpoints[0],
                    endpoints[1],
                    request.departure_date.isoformat(),
                    return_date=request.return_date.isoformat(),
                    cabin="economy",
                    passengers=passengers,
                    sort=SORT_CHEAPEST,
                    transport=transport,
                )
            else:
                legs = [
                    SearchLeg(
                        from_airport=endpoints[0],
                        to_airport=endpoints[1],
                        date=request.departure_date.isoformat(),
                    ),
                    SearchLeg(
                        from_airport=endpoints[2],
                        to_airport=endpoints[3],
                        date=request.return_date.isoformat(),
                    ),
                ]
                result = await asyncio.to_thread(
                    self._search_legs,
                    legs,
                    cabin="economy",
                    passengers=passengers,
                    sort=SORT_CHEAPEST,
                    transport=transport,
                )
        except (
            SwoopRateLimitError,
            SwoopHTTPError,
            SwoopParseError,
            SwoopUpstreamError,
            SwoopError,
            TimeoutError,
        ) as exc:
            raise FlightProviderUnavailableError(
                "Swoop flight search is temporarily unavailable"
            ) from exc
        except (OSError, ValueError) as exc:
            raise FlightProviderError("Swoop flight search failed") from exc

        if not isinstance(result, SearchResult):
            raise FlightProviderError("Swoop returned an unexpected search result")
        options: list[FlightOption] = []
        fetched_at = self._now()
        for raw_option in result.results[:MAX_SWOOP_RESULTS_TO_CONSIDER]:
            try:
                options.append(
                    parse_swoop_option(
                        raw_option,
                        adults=request.adults,
                        fetched_at=fetched_at,
                    )
                )
            except (FlightProviderError, ValidationError, TypeError, ValueError):
                logger.warning("swoop_option_skipped reason=malformed")
        if result.results and not options:
            raise FlightProviderError("Swoop returned no valid flight options")
        logger.info(
            "swoop_results_received provider_count=%s normalized_count=%s",
            len(result.results),
            len(options),
        )
        return options

    async def aclose(self) -> None:
        close = getattr(self._airport_resolver, "aclose", None)
        if close is not None:
            result = close()
            if isawaitable(result):
                await result

    async def _resolve_endpoints(
        self,
        request: FlightSearchRequest,
    ) -> list[str]:
        inputs = [
            (request.origin, request.origin_country_hint),
            (request.destination, request.destination_country_hint),
        ]
        if request.return_date is not None:
            inputs.extend(
                [
                    (
                        request.return_origin or request.destination,
                        request.return_origin_country_hint,
                    ),
                    (
                        request.return_destination or request.origin,
                        request.return_destination_country_hint,
                    ),
                ]
            )

        cache: dict[tuple[str, str], str] = {}
        resolved: list[str] = []
        for query, country_hint in inputs:
            cache_key = (
                " ".join(query.casefold().split()),
                (country_hint or "").strip().upper(),
            )
            code = cache.get(cache_key)
            if code is None:
                code = await self._airport_resolver.resolve_airport(
                    query,
                    country_hint=country_hint,
                )
                cache[cache_key] = code
            resolved.append(code)
        return resolved


def parse_swoop_option(
    option: TripOption,
    *,
    adults: int,
    fetched_at: datetime,
) -> FlightOption:
    """Map one typed Swoop option without exposing selectors or raw RPC data."""

    if not isinstance(option, TripOption):
        raise FlightProviderError("Swoop option had an unexpected type")
    if not option.legs:
        raise FlightProviderError("Swoop option omitted trip legs")
    total_price = _money(option.price)
    currency = _currency(option.currency)
    slices = [parse_swoop_leg(leg) for leg in option.legs]
    airline_names = _unique_airline_names(option, slices)
    provider_offer_id = _stable_result_id(
        slices=slices,
        price=total_price,
        currency=currency,
    )
    return FlightOption(
        provider="swoop",
        provider_offer_id=provider_offer_id,
        origin_code=slices[0].origin_code,
        destination_code=slices[0].destination_code,
        adults=adults,
        total_duration_minutes=sum(item.duration_minutes for item in slices),
        stops=sum(item.stops for item in slices),
        total_price=float(total_price),
        currency=currency,
        price_type="shopping_total",
        airline_names=airline_names,
        slices=slices,
        fetched_at=fetched_at,
    )


def parse_swoop_leg(leg: Any) -> FlightSlice:
    itinerary = getattr(leg, "itinerary", None)
    if not isinstance(itinerary, Itinerary):
        raise FlightProviderError("Swoop trip leg omitted its itinerary")
    if not itinerary.segments:
        raise FlightProviderError("Swoop itinerary omitted flight segments")
    segments = [parse_swoop_segment(segment) for segment in itinerary.segments]
    duration = _positive_int(itinerary.travel_time, "itinerary duration")
    stops = _non_negative_int(
        itinerary.stop_count
        if itinerary.stop_count is not None
        else len(itinerary.layovers),
        "stop count",
    )
    layovers = [
        FlightLayover(
            airport_code=_optional_iata(
                layover.departure_airport_code or layover.arrival_airport_code
            ),
            airport_name=_clean_string(
                layover.departure_airport_name or layover.arrival_airport_name
            ),
            city=_clean_string(
                layover.departure_airport_city or layover.arrival_airport_city
            ),
            duration_minutes=_non_negative_int(
                layover.minutes,
                "layover duration",
            ),
            is_overnight=bool(layover.is_overnight),
        )
        for layover in itinerary.layovers
    ]
    return FlightSlice(
        origin_code=segments[0].origin_code,
        destination_code=segments[-1].destination_code,
        departure_at=segments[0].departure_at,
        arrival_at=segments[-1].arrival_at,
        duration_minutes=duration,
        stops=stops,
        segments=segments,
        layovers=layovers,
    )


def parse_swoop_segment(segment: Any) -> FlightSegment:
    if not isinstance(segment, Segment):
        raise FlightProviderError("Swoop itinerary contained an invalid segment")
    departure_at = _swoop_datetime(
        segment.departure_date,
        segment.departure_time,
        "segment departure",
    )
    arrival_at = _swoop_datetime(
        segment.arrival_date,
        segment.arrival_time,
        "segment arrival",
    )
    return FlightSegment(
        origin_code=_iata(segment.departure_airport_code, "segment origin"),
        destination_code=_iata(
            segment.arrival_airport_code,
            "segment destination",
        ),
        departure_at=departure_at,
        arrival_at=arrival_at,
        duration_minutes=_positive_int(segment.travel_time, "segment duration"),
        airline_code=_optional_airline_code(segment.airline),
        airline_name=_clean_string(segment.airline_name),
        operator_name=_clean_string(segment.operator),
        flight_number=_clean_string(segment.flight_number),
        aircraft=_clean_string(segment.aircraft),
    )


def _stable_result_id(
    *,
    slices: list[FlightSlice],
    price: Decimal,
    currency: str,
) -> str:
    identity = {
        "currency": currency,
        "price": str(price),
        "slices": [
            {
                "origin": item.origin_code,
                "destination": item.destination_code,
                "departure": item.departure_at.isoformat(),
                "segments": [
                    {
                        "airline": segment.airline_code,
                        "flight": segment.flight_number,
                        "origin": segment.origin_code,
                        "destination": segment.destination_code,
                        "departure": segment.departure_at.isoformat(),
                    }
                    for segment in item.segments
                ],
            }
            for item in slices
        ],
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return f"swoop_{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def _unique_airline_names(
    option: TripOption,
    slices: list[FlightSlice],
) -> list[str]:
    values: list[str] = []
    for leg in option.legs:
        itinerary = leg.itinerary
        if itinerary is None:
            continue
        for name in itinerary.airline_names:
            normalized = _clean_string(name)
            if normalized and normalized not in values:
                values.append(normalized)
    for flight_slice in slices:
        for segment in flight_slice.segments:
            for value in (segment.airline_name, segment.operator_name):
                if value and value not in values:
                    values.append(value)
    return values


def _money(value: Any) -> Decimal:
    if value is None or isinstance(value, bool):
        raise FlightProviderError("Swoop option omitted its shopping total")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise FlightProviderError("Swoop option contained an invalid price") from exc
    if not amount.is_finite() or amount < 0:
        raise FlightProviderError("Swoop option contained an invalid price")
    return amount.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _currency(value: Any) -> str:
    if not isinstance(value, str):
        raise FlightProviderError("Swoop option omitted its currency")
    normalized = value.strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise FlightProviderError("Swoop option contained an invalid currency")
    return normalized


def _swoop_datetime(
    date_value: Any,
    time_value: Any,
    label: str,
) -> datetime:
    try:
        year, month, day = date_value
        hour, minute = time_value
        return datetime(
            int(year),
            int(month),
            int(day),
            int(hour),
            int(minute),
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise FlightProviderError(f"Swoop option contained an invalid {label}") from exc


def _iata(value: Any, label: str) -> str:
    code = _optional_iata(value)
    if code is None:
        raise FlightProviderError(f"Swoop option omitted {label}")
    return code


def _optional_iata(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().upper()
    return normalized if len(normalized) == 3 and normalized.isalpha() else None


def _optional_airline_code(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().upper()
    return normalized if len(normalized) == 2 and normalized.isalnum() else None


def _positive_int(value: Any, label: str) -> int:
    parsed = _non_negative_int(value, label)
    if parsed < 1:
        raise FlightProviderError(f"Swoop option contained an invalid {label}")
    return parsed


def _non_negative_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise FlightProviderError(f"Swoop option contained an invalid {label}")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise FlightProviderError(f"Swoop option contained an invalid {label}") from exc
    if parsed < 0:
        raise FlightProviderError(f"Swoop option contained an invalid {label}")
    return parsed


def _clean_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
