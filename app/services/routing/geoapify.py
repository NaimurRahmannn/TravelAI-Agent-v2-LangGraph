import asyncio
import logging
import math
import time
from collections.abc import Awaitable, Callable, Mapping
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus

import httpx

from app.models.itinerary import TravelMode
from app.services.routing.base import (
    RouteResult,
    RoutingAuthenticationError,
    RoutingProviderError,
    RoutingProviderUnavailableError,
    RoutingRateLimitError,
)

GEOAPIFY_ROUTING_URL = "https://api.geoapify.com/v1/routing"
MAX_REQUEST_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 0.25
MAX_RETRY_AFTER_SECONDS = 5.0
DEFAULT_MIN_REQUEST_INTERVAL_SECONDS = 0.21


class _CredentialRedactionFilter(logging.Filter):
    """Prevent the apiKey query parameter from appearing in HTTP logs."""

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


class GeoapifyRoutingProvider:
    """Fetch pair-by-pair travel estimates from Geoapify Routing."""

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        min_request_interval_seconds: float = DEFAULT_MIN_REQUEST_INTERVAL_SECONDS,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Geoapify API key is required")
        self._api_key = api_key.strip()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=3.0, read=7.0),
        )
        self._sleep = sleep
        self._monotonic = monotonic
        self._minimum_interval = max(0.0, min_request_interval_seconds)
        self._pace_lock = asyncio.Lock()
        self._next_request_at = 0.0

    async def get_route(
        self,
        *,
        origin_latitude: float,
        origin_longitude: float,
        destination_latitude: float,
        destination_longitude: float,
        mode: TravelMode,
    ) -> RouteResult | None:
        payload = await self._request_json(
            {
                "waypoints": (
                    f"{origin_latitude},{origin_longitude}|"
                    f"{destination_latitude},{destination_longitude}"
                ),
                "mode": mode,
                "format": "json",
                "units": "metric",
                "apiKey": self._api_key,
            }
        )
        return parse_geoapify_route(payload)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _pace_request(self) -> None:
        async with self._pace_lock:
            now = self._monotonic()
            delay = max(0.0, self._next_request_at - now)
            if delay:
                await self._sleep(delay)
                now = self._monotonic()
            self._next_request_at = max(now, self._next_request_at) + self._minimum_interval

    async def _request_json(self, params: dict[str, object]) -> Mapping[str, Any]:
        for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
            await self._pace_request()
            try:
                httpx_logger = logging.getLogger("httpx")
                redaction_filter = _CredentialRedactionFilter(self._api_key)
                httpx_logger.addFilter(redaction_filter)
                try:
                    response = await self._client.get(
                        GEOAPIFY_ROUTING_URL,
                        params=params,
                    )
                finally:
                    httpx_logger.removeFilter(redaction_filter)
            except httpx.TransportError as exc:
                if attempt < MAX_REQUEST_ATTEMPTS:
                    await self._sleep(RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)))
                    continue
                raise RoutingProviderUnavailableError(
                    "Geoapify routing request failed"
                ) from exc

            if response.status_code in {401, 403}:
                raise RoutingAuthenticationError(
                    "Geoapify rejected the configured credential"
                )
            if response.status_code == 429:
                if attempt < MAX_REQUEST_ATTEMPTS:
                    await self._sleep(_retry_delay(response, attempt))
                    continue
                raise RoutingRateLimitError("Geoapify routing rate limit exceeded")
            if 500 <= response.status_code < 600:
                if attempt < MAX_REQUEST_ATTEMPTS:
                    await self._sleep(_retry_delay(response, attempt))
                    continue
                raise RoutingProviderUnavailableError(
                    "Geoapify routing service unavailable"
                )
            if response.status_code >= 400:
                raise RoutingProviderError(
                    f"Geoapify routing request rejected with status {response.status_code}"
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise RoutingProviderError("Geoapify returned invalid routing JSON") from exc
            if not isinstance(payload, Mapping):
                raise RoutingProviderError(
                    "Geoapify returned an unexpected routing payload"
                )
            return payload

        raise RoutingProviderUnavailableError("Geoapify routing request failed")


def parse_geoapify_route(payload: Mapping[str, Any]) -> RouteResult | None:
    """Normalize the first pair route without retaining provider response data."""

    results = payload.get("results")
    if not isinstance(results, list):
        raise RoutingProviderError("Geoapify routing response omitted results")
    if not results:
        return None
    route = results[0]
    if not isinstance(route, Mapping):
        raise RoutingProviderError("Geoapify returned a malformed route")

    metrics: Mapping[str, Any] = route
    legs = route.get("legs")
    if isinstance(legs, list) and legs and isinstance(legs[0], Mapping):
        metrics = legs[0]
    distance = _nonnegative_number(metrics.get("distance"))
    duration = _nonnegative_number(metrics.get("time"))
    if distance is None or duration is None:
        raise RoutingProviderError("Geoapify route omitted usable metrics")
    return RouteResult(
        distance_meters=distance,
        duration_seconds=int(round(duration)),
    )


def _nonnegative_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed < 0:
        return None
    return parsed


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            delay = float(retry_after)
        except ValueError:
            try:
                when = parsedate_to_datetime(retry_after)
                delay = when.timestamp() - time.time()
            except (TypeError, ValueError, OverflowError):
                delay = 0.0
        if delay > 0:
            return min(delay, MAX_RETRY_AFTER_SECONDS)
    return RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
