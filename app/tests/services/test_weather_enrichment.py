import asyncio
from datetime import UTC, date, datetime

from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    DailyWeather,
    ItineraryDay,
    ResolvedPlace,
    TripPlan,
)
from app.services.weather import (
    LocationForecast,
    WeatherProviderError,
    WeatherProviderUnavailableError,
)
from app.services.weather_enrichment import (
    enrich_trip_weather,
    select_representative_place,
)


def _place(
    place_id: str,
    *,
    city: str = "Bangkok",
    country: str = "Thailand",
    latitude: float = 13.75,
    longitude: float = 100.5,
    status: str = "resolved",
) -> ResolvedPlace:
    return ResolvedPlace(
        provider="geoapify",
        provider_place_id=place_id,
        name=place_id,
        city=city,
        country=country,
        latitude=latitude,
        longitude=longitude,
        resolution_status=status,
    )


def _activity(place: ResolvedPlace | None) -> Activity:
    return Activity(
        name=place.name if place else "Airport transfer",
        category="visit" if place else "transport",
        place=place,
        place_resolution_status=place.resolution_status if place else "unresolved",
    )


def _day(
    day_number: int,
    travel_date: date | None,
    city: str,
    *places: ResolvedPlace | None,
) -> ItineraryDay:
    return ItineraryDay(
        day_number=day_number,
        date=travel_date,
        city=city,
        activities=[_activity(place) for place in places],
    )


def _plan(*days: ItineraryDay) -> TripPlan:
    return TripPlan(
        title="Thailand Plan",
        destination="Thailand",
        duration_days=len(days),
        travelers=2,
        preferences=[],
        days=list(days),
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Activities", amount_usd=100)],
            estimated_total_usd=100,
        ),
        practical_notes=[],
    )


def _weather(travel_date: date, condition: str = "Clouds") -> DailyWeather:
    return DailyWeather(
        provider="openweather",
        date=travel_date,
        condition=condition,
        min_temperature_c=26,
        max_temperature_c=32,
        precipitation_probability_pct=30,
        wind_speed_mps=4,
        fetched_at=datetime(2026, 8, 19, tzinfo=UTC),
    )


class FakeProvider:
    def __init__(self, results=None, errors=None):
        self.results = results or {}
        self.errors = errors or {}
        self.calls = []

    async def get_forecast(self, *, latitude, longitude):
        key = (latitude, longitude)
        self.calls.append(key)
        error = self.errors.get(key)
        if error:
            raise error
        return self.results.get(key, LocationForecast(0, {}))


def test_representative_place_prefers_matching_day_city():
    fallback = _place("fallback", city="Pattaya", latitude=12.9)
    matching = _place("matching", city="Bangkok", latitude=13.7)
    day = _day(1, date(2026, 8, 21), "Bangkok", fallback, matching)

    selected = select_representative_place(day)

    assert selected == matching


def test_partial_place_is_ignored_and_no_resolved_place_is_skipped():
    partial = _place("partial", status="partially_resolved")
    plan = _plan(_day(1, date(2026, 8, 21), "Bangkok", partial, None))
    provider = FakeProvider()

    enriched = asyncio.run(enrich_trip_weather(plan, provider))

    assert provider.calls == []
    assert enriched.days[0].weather is None
    assert enriched.days[0].weather_status == "skipped"


def test_missing_authoritative_day_date_is_skipped():
    plan = _plan(_day(1, None, "Bangkok", _place("temple")))
    provider = FakeProvider()

    enriched = asyncio.run(enrich_trip_weather(plan, provider))

    assert provider.calls == []
    assert enriched.days[0].weather_status == "skipped"


def test_same_location_is_requested_once_and_reused_across_days():
    first_date = date(2026, 8, 21)
    second_date = date(2026, 8, 22)
    first_place = _place("first", latitude=13.75, longitude=100.5)
    second_place = _place("second", latitude=13.76, longitude=100.51)
    forecast = LocationForecast(
        timezone_offset_seconds=25200,
        daily={
            first_date: _weather(first_date, "Rain"),
            second_date: _weather(second_date, "Clouds"),
        },
    )
    provider = FakeProvider({(13.75, 100.5): forecast})
    plan = _plan(
        _day(1, first_date, "Bangkok", first_place),
        _day(2, second_date, "Bangkok", second_place),
    )

    enriched = asyncio.run(enrich_trip_weather(plan, provider))

    assert provider.calls == [(13.75, 100.5)]
    assert [day.weather_status for day in enriched.days] == ["resolved", "resolved"]
    assert [day.weather.condition for day in enriched.days] == ["Rain", "Clouds"]


def test_forecast_horizon_supports_partial_trip_coverage():
    first_date = date(2026, 8, 21)
    place = _place("temple")
    provider = FakeProvider(
        {
            (13.75, 100.5): LocationForecast(
                timezone_offset_seconds=25200,
                daily={first_date: _weather(first_date)},
            )
        }
    )
    plan = _plan(
        _day(1, first_date, "Bangkok", place),
        _day(2, date(2026, 8, 22), "Bangkok", place),
        _day(3, date(2026, 8, 23), "Bangkok", place),
    )

    enriched = asyncio.run(enrich_trip_weather(plan, provider))

    assert [day.weather_status for day in enriched.days] == [
        "resolved",
        "outside_forecast_horizon",
        "outside_forecast_horizon",
    ]
    assert enriched.days[0].weather.date == first_date
    assert enriched.days[1].weather is None


def test_provider_unavailable_opens_circuit_but_preserves_prior_success():
    dates = [date(2026, 8, day) for day in (21, 22, 23)]
    bangkok = _place("bangkok", city="Bangkok", latitude=13.75)
    pattaya = _place("pattaya", city="Pattaya", latitude=12.92)
    chiang_mai = _place("chiang-mai", city="Chiang Mai", latitude=18.79)
    provider = FakeProvider(
        results={
            (13.75, 100.5): LocationForecast(
                25200,
                {dates[0]: _weather(dates[0])},
            )
        },
        errors={
            (12.92, 100.5): WeatherProviderUnavailableError("outage"),
        },
    )
    plan = _plan(
        _day(1, dates[0], "Bangkok", bangkok),
        _day(2, dates[1], "Pattaya", pattaya),
        _day(3, dates[2], "Chiang Mai", chiang_mai),
    )

    enriched = asyncio.run(enrich_trip_weather(plan, provider))

    assert provider.calls == [(13.75, 100.5), (12.92, 100.5)]
    assert [day.weather_status for day in enriched.days] == [
        "resolved",
        "unavailable",
        "unavailable",
    ]


def test_normal_provider_error_does_not_open_trip_circuit():
    dates = [date(2026, 8, day) for day in (21, 22)]
    first = _place("first", city="Bangkok", latitude=13.75)
    second = _place("second", city="Pattaya", latitude=12.92)
    provider = FakeProvider(
        errors={(13.75, 100.5): WeatherProviderError("bad payload")},
        results={
            (12.92, 100.5): LocationForecast(
                25200,
                {dates[1]: _weather(dates[1])},
            )
        },
    )
    plan = _plan(
        _day(1, dates[0], "Bangkok", first),
        _day(2, dates[1], "Pattaya", second),
    )

    enriched = asyncio.run(enrich_trip_weather(plan, provider))

    assert provider.calls == [(13.75, 100.5), (12.92, 100.5)]
    assert [day.weather_status for day in enriched.days] == [
        "unavailable",
        "resolved",
    ]
