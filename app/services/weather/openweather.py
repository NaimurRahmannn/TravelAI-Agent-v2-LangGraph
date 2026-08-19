import asyncio
import logging
import math
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus

import httpx

from app.models import DailyWeather
from app.services.weather.base import (
    LocationForecast,
    OpenWeatherAuthenticationError,
    OpenWeatherRateLimitError,
    WeatherProviderError,
    WeatherProviderUnavailableError,
)

OPENWEATHER_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
MAX_REQUEST_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 0.25
MAX_RETRY_AFTER_SECONDS = 5.0


@dataclass(frozen=True)
class _ForecastEntry:
    local_datetime: datetime
    min_temperature_c: float
    max_temperature_c: float
    condition: str | None
    description: str | None
    precipitation_probability_pct: float | None
    wind_speed_mps: float | None


class _CredentialRedactionFilter(logging.Filter):
    """Prevent the appid query parameter from appearing in HTTP client logs."""

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


class OpenWeatherProvider:
    """Fetch and aggregate OpenWeather's coordinate-based 5-day forecast."""

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not api_key.strip():
            raise ValueError("OpenWeather API key is required")
        self._api_key = api_key.strip()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=3.0, read=7.0),
        )
        self._sleep = sleep
        self._now = now

    async def get_forecast(
        self,
        *,
        latitude: float,
        longitude: float,
    ) -> LocationForecast:
        payload = await self._request_json(
            {
                "lat": latitude,
                "lon": longitude,
                "appid": self._api_key,
                "units": "metric",
            }
        )
        return parse_openweather_forecast(payload, fetched_at=self._now())

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request_json(self, params: dict[str, object]) -> Mapping[str, Any]:
        for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
            try:
                httpx_logger = logging.getLogger("httpx")
                redaction_filter = _CredentialRedactionFilter(self._api_key)
                httpx_logger.addFilter(redaction_filter)
                try:
                    response = await self._client.get(
                        OPENWEATHER_FORECAST_URL,
                        params=params,
                    )
                finally:
                    httpx_logger.removeFilter(redaction_filter)
            except httpx.TransportError as exc:
                if attempt < MAX_REQUEST_ATTEMPTS:
                    await self._sleep(RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)))
                    continue
                raise WeatherProviderUnavailableError(
                    "OpenWeather request failed"
                ) from exc

            if response.status_code in {401, 403}:
                raise OpenWeatherAuthenticationError(
                    "OpenWeather rejected the configured credential"
                )
            if response.status_code == 429:
                if attempt < MAX_REQUEST_ATTEMPTS:
                    await self._sleep(_retry_delay(response, attempt))
                    continue
                raise OpenWeatherRateLimitError("OpenWeather rate limit exceeded")
            if 500 <= response.status_code < 600:
                if attempt < MAX_REQUEST_ATTEMPTS:
                    await self._sleep(_retry_delay(response, attempt))
                    continue
                raise WeatherProviderUnavailableError(
                    "OpenWeather service unavailable"
                )
            if response.status_code >= 400:
                raise WeatherProviderError(
                    f"OpenWeather request rejected with status {response.status_code}"
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise WeatherProviderError("OpenWeather returned invalid JSON") from exc
            if not isinstance(payload, Mapping):
                raise WeatherProviderError("OpenWeather returned an unexpected payload")
            return payload

        raise WeatherProviderUnavailableError("OpenWeather request failed")


def parse_openweather_forecast(
    payload: Mapping[str, Any],
    *,
    fetched_at: datetime,
) -> LocationForecast:
    """Aggregate provider entries by destination-local calendar date."""

    city = payload.get("city")
    timezone_offset = _integer(city.get("timezone")) if isinstance(city, Mapping) else None
    if timezone_offset is None:
        raise WeatherProviderError("OpenWeather response omitted location timezone")
    if not -86400 < timezone_offset < 86400:
        raise WeatherProviderError("OpenWeather returned an invalid location timezone")
    raw_entries = payload.get("list")
    if not isinstance(raw_entries, list):
        raise WeatherProviderError("OpenWeather response omitted forecast entries")

    grouped: dict[date, list[_ForecastEntry]] = {}
    for raw_entry in raw_entries:
        entry = _parse_entry(raw_entry, timezone_offset)
        if entry is None:
            continue
        grouped.setdefault(entry.local_datetime.date(), []).append(entry)
    if not grouped:
        raise WeatherProviderError("OpenWeather returned no usable forecast entries")

    daily: dict[date, DailyWeather] = {}
    for local_date, entries in grouped.items():
        aggregated = _aggregate_day(local_date, entries, fetched_at=fetched_at)
        if aggregated is not None:
            daily[local_date] = aggregated
    if not daily:
        raise WeatherProviderError("OpenWeather returned no usable daily forecasts")
    return LocationForecast(
        timezone_offset_seconds=timezone_offset,
        daily=daily,
    )


def _parse_entry(raw_entry: object, timezone_offset: int) -> _ForecastEntry | None:
    if not isinstance(raw_entry, Mapping):
        return None
    timestamp = _number(raw_entry.get("dt"))
    main = raw_entry.get("main")
    if timestamp is None or not isinstance(main, Mapping):
        return None
    minimum = _number(main.get("temp_min"))
    maximum = _number(main.get("temp_max"))
    if minimum is None or maximum is None or maximum < minimum:
        return None

    location_timezone = timezone(timedelta(seconds=timezone_offset))
    local_datetime = datetime.fromtimestamp(
        timestamp,
        location_timezone,
    )
    condition = None
    description = None
    weather_items = raw_entry.get("weather")
    if isinstance(weather_items, list) and weather_items:
        weather = weather_items[0]
        if isinstance(weather, Mapping):
            condition = _text(weather.get("main"))
            description = _text(weather.get("description"))

    pop = _number(raw_entry.get("pop"))
    precipitation = (
        round(min(1.0, max(0.0, pop)) * 100, 2)
        if pop is not None
        else None
    )
    wind = raw_entry.get("wind")
    wind_speed = _number(wind.get("speed")) if isinstance(wind, Mapping) else None
    if wind_speed is not None and wind_speed < 0:
        wind_speed = None

    return _ForecastEntry(
        local_datetime=local_datetime,
        min_temperature_c=minimum,
        max_temperature_c=maximum,
        condition=condition,
        description=description,
        precipitation_probability_pct=precipitation,
        wind_speed_mps=wind_speed,
    )


def _aggregate_day(
    local_date: date,
    entries: list[_ForecastEntry],
    *,
    fetched_at: datetime,
) -> DailyWeather | None:
    condition_entries = [entry for entry in entries if entry.condition]
    if not condition_entries:
        return None
    noon = datetime.combine(
        local_date,
        time(hour=12),
        tzinfo=entries[0].local_datetime.tzinfo,
    )
    representative = min(
        condition_entries,
        key=lambda entry: (
            abs((entry.local_datetime - noon).total_seconds()),
            entry.local_datetime,
        ),
    )
    precipitation_values = [
        entry.precipitation_probability_pct
        for entry in entries
        if entry.precipitation_probability_pct is not None
    ]
    wind_values = [
        entry.wind_speed_mps
        for entry in entries
        if entry.wind_speed_mps is not None
    ]
    return DailyWeather(
        provider="openweather",
        date=local_date,
        condition=representative.condition or "Unknown",
        description=representative.description,
        min_temperature_c=min(entry.min_temperature_c for entry in entries),
        max_temperature_c=max(entry.max_temperature_c for entry in entries),
        precipitation_probability_pct=(
            max(precipitation_values) if precipitation_values else None
        ),
        wind_speed_mps=max(wind_values) if wind_values else None,
        fetched_at=fetched_at,
    )


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _integer(value: object) -> int | None:
    number = _number(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized or None


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            delay = float(retry_after)
        except ValueError:
            try:
                when = parsedate_to_datetime(retry_after)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=UTC)
                delay = (when - datetime.now(UTC)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                delay = -1
        if 0 <= delay <= MAX_RETRY_AFTER_SECONDS:
            return delay
    return RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
