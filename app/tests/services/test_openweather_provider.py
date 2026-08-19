import asyncio
from datetime import UTC, date, datetime

import httpx
import pytest

from app.services.weather import (
    OpenWeatherAuthenticationError,
    OpenWeatherProvider,
    OpenWeatherRateLimitError,
    WeatherProviderError,
    WeatherProviderUnavailableError,
)
from app.services.weather.openweather import parse_openweather_forecast

FETCHED_AT = datetime(2026, 8, 19, 12, tzinfo=UTC)


def _entry(
    timestamp: str,
    *,
    minimum: float = 26,
    maximum: float = 31,
    condition: str = "Clouds",
    description: object = "scattered clouds",
    pop: object = 0.3,
    wind: object = 4.5,
) -> dict:
    data = {
        "dt": int(datetime.fromisoformat(timestamp).timestamp()),
        "main": {"temp_min": minimum, "temp_max": maximum},
        "weather": [{"main": condition, "description": description}],
    }
    if pop is not ...:
        data["pop"] = pop
    if wind is not ...:
        data["wind"] = {"speed": wind}
    return data


def _payload(*entries: dict, timezone: int = 0) -> dict:
    return {
        "city": {"timezone": timezone},
        "list": list(entries),
    }


def _forecast_with_handler(handler, *, sleep=None):
    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            provider = OpenWeatherProvider(
                "test-weather-key",
                client=client,
                sleep=sleep or (lambda _: asyncio.sleep(0)),
                now=lambda: FETCHED_AT,
            )
            return await provider.get_forecast(latitude=13.75, longitude=100.5)

    return asyncio.run(run())


def test_provider_requests_metric_coordinate_forecast_and_parses_response():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json=_payload(_entry("2026-08-21T12:00:00+00:00")),
        )

    forecast = _forecast_with_handler(handler)

    assert requests[0].url.path == "/data/2.5/forecast"
    assert requests[0].url.params["lat"] == "13.75"
    assert requests[0].url.params["lon"] == "100.5"
    assert requests[0].url.params["appid"] == "test-weather-key"
    assert requests[0].url.params["units"] == "metric"
    weather = forecast.daily[date(2026, 8, 21)]
    assert weather.provider == "openweather"
    assert weather.min_temperature_c == 26
    assert weather.max_temperature_c == 31
    assert weather.precipitation_probability_pct == 30
    assert weather.wind_speed_mps == 4.5
    assert weather.fetched_at == FETCHED_AT


def test_daily_aggregation_uses_extremes_and_nearest_noon_condition():
    forecast = parse_openweather_forecast(
        _payload(
            _entry(
                "2026-08-21T06:00:00+00:00",
                minimum=25,
                maximum=29,
                condition="Rain",
                pop=0.72,
                wind=3,
            ),
            _entry(
                "2026-08-21T12:00:00+00:00",
                minimum=27,
                maximum=33,
                condition="Clouds",
                description="broken clouds",
                pop=0.2,
                wind=8,
            ),
            _entry(
                "2026-08-21T18:00:00+00:00",
                minimum=24,
                maximum=30,
                condition="Clear",
                pop=1.5,
                wind=5,
            ),
        ),
        fetched_at=FETCHED_AT,
    )

    weather = forecast.daily[date(2026, 8, 21)]
    assert weather.min_temperature_c == 24
    assert weather.max_temperature_c == 33
    assert weather.precipitation_probability_pct == 100
    assert weather.wind_speed_mps == 8
    assert weather.condition == "Clouds"
    assert weather.description == "broken clouds"


def test_entries_use_destination_local_date_across_utc_midnight_boundary():
    forecast = parse_openweather_forecast(
        _payload(
            _entry("2026-08-20T18:00:00+00:00", condition="Rain"),
            _entry("2026-08-21T03:00:00+00:00", condition="Clear"),
            timezone=7 * 60 * 60,
        ),
        fetched_at=FETCHED_AT,
    )

    assert list(forecast.daily) == [date(2026, 8, 21)]
    assert forecast.timezone_offset_seconds == 25200
    assert forecast.daily[date(2026, 8, 21)].condition == "Clear"


def test_missing_optional_values_remain_none_and_do_not_crash():
    forecast = parse_openweather_forecast(
        _payload(
            _entry(
                "2026-08-21T12:00:00+00:00",
                description=None,
                pop=...,
                wind=...,
            )
        ),
        fetched_at=FETCHED_AT,
    )

    weather = forecast.daily[date(2026, 8, 21)]
    assert weather.description is None
    assert weather.precipitation_probability_pct is None
    assert weather.wind_speed_mps is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"city": {"timezone": 0}, "list": "invalid"},
        {"city": {"timezone": 90000}, "list": []},
        {"city": {"timezone": 0}, "list": [{"unexpected": "entry"}]},
        {
            "city": {"timezone": 0},
            "list": [
                {
                    "dt": int(FETCHED_AT.timestamp()),
                    "main": {"temp_min": 20, "temp_max": 25},
                    "weather": [],
                }
            ],
        },
    ],
)
def test_malformed_payloads_raise_safe_provider_error(payload):
    with pytest.raises(WeatherProviderError, match="OpenWeather") as error:
        parse_openweather_forecast(payload, fetched_at=FETCHED_AT)

    assert "test-weather-key" not in str(error.value)


@pytest.mark.parametrize(
    ("status_code", "error_type", "expected_calls"),
    [
        (401, OpenWeatherAuthenticationError, 1),
        (403, OpenWeatherAuthenticationError, 1),
        (429, OpenWeatherRateLimitError, 3),
        (500, WeatherProviderUnavailableError, 3),
        (503, WeatherProviderUnavailableError, 3),
    ],
)
def test_http_failures_follow_bounded_retry_policy(
    status_code,
    error_type,
    expected_calls,
):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status_code, headers={"Retry-After": "0"})

    with pytest.raises(error_type) as error:
        _forecast_with_handler(handler)

    assert calls == expected_calls
    assert "test-weather-key" not in str(error.value)


@pytest.mark.parametrize(
    "transport_error",
    [httpx.ReadTimeout("timeout"), httpx.ConnectError("down")],
)
def test_transport_failures_retry_then_raise_safe_unavailable_error(transport_error):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        raise transport_error

    with pytest.raises(WeatherProviderUnavailableError, match="request failed"):
        _forecast_with_handler(handler)

    assert calls == 3


def test_retryable_failure_can_recover():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json=_payload(_entry("2026-08-21T12:00:00+00:00")),
        )

    forecast = _forecast_with_handler(handler)

    assert calls == 2
    assert date(2026, 8, 21) in forecast.daily
