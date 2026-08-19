from dataclasses import dataclass
from datetime import date
from typing import Protocol

from app.models import DailyWeather


class WeatherProviderError(RuntimeError):
    """Base error for safe weather-provider failures."""


class WeatherProviderUnavailableError(WeatherProviderError):
    """A provider-wide failure that should open a trip-local circuit."""


class OpenWeatherAuthenticationError(WeatherProviderUnavailableError):
    """OpenWeather rejected the configured server-side credential."""


class OpenWeatherRateLimitError(WeatherProviderUnavailableError):
    """OpenWeather rate limiting persisted after bounded retries."""


@dataclass(frozen=True)
class LocationForecast:
    """Daily forecasts for one provider location and timezone."""

    timezone_offset_seconds: int
    daily: dict[date, DailyWeather]


class WeatherProvider(Protocol):
    """Provider boundary for one coordinate-based location forecast."""

    async def get_forecast(
        self,
        *,
        latitude: float,
        longitude: float,
    ) -> LocationForecast:
        ...
