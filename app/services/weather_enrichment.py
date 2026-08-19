from app.core.logging import get_logger
from app.models import ItineraryDay, ResolvedPlace, TripPlan
from app.services.places import normalize_place_text
from app.services.weather import (
    LocationForecast,
    WeatherProvider,
    WeatherProviderError,
    WeatherProviderUnavailableError,
)

logger = get_logger(__name__)


async def enrich_trip_weather(
    trip_plan: TripPlan,
    provider: WeatherProvider,
) -> TripPlan:
    """Attach trusted daily forecasts while preserving partial trip success."""

    plan_data = trip_plan.model_dump()
    for day_data in plan_data["days"]:
        day_data["weather"] = None
        day_data["weather_status"] = "skipped"

    forecasts: dict[str, LocationForecast] = {}
    circuit_open = False

    for day_index, day in enumerate(trip_plan.days):
        day_data = plan_data["days"][day_index]
        if day.date is None:
            continue
        place = select_representative_place(day)
        if place is None:
            continue

        cache_key = weather_deduplication_key(place)
        forecast = forecasts.get(cache_key)
        if forecast is None:
            if circuit_open:
                day_data["weather_status"] = "unavailable"
                continue
            try:
                forecast = await provider.get_forecast(
                    latitude=place.latitude,
                    longitude=place.longitude,
                )
                forecasts[cache_key] = forecast
            except WeatherProviderUnavailableError as exc:
                circuit_open = True
                day_data["weather_status"] = "unavailable"
                logger.warning(
                    "weather_provider_circuit_opened day=%s city=%s error_type=%s",
                    day.day_number,
                    day.city,
                    type(exc).__name__,
                )
                continue
            except WeatherProviderError as exc:
                day_data["weather_status"] = "unavailable"
                logger.warning(
                    "weather_resolution_error day=%s city=%s error_type=%s",
                    day.day_number,
                    day.city,
                    type(exc).__name__,
                )
                continue
            except Exception as exc:
                day_data["weather_status"] = "unavailable"
                logger.warning(
                    "weather_resolution_error day=%s city=%s error_type=%s",
                    day.day_number,
                    day.city,
                    type(exc).__name__,
                )
                continue

        daily_weather = forecast.daily.get(day.date)
        if daily_weather is None:
            day_data["weather_status"] = "outside_forecast_horizon"
            continue
        day_data["weather"] = daily_weather.model_dump()
        day_data["weather_status"] = "resolved"

    return TripPlan.model_validate(plan_data)


def select_representative_place(day: ItineraryDay) -> ResolvedPlace | None:
    """Choose one fully resolved place, preferring the itinerary-day city."""

    resolved_places = [
        activity.place
        for activity in day.activities
        if activity.place is not None
        and activity.place_resolution_status == "resolved"
        and activity.place.resolution_status == "resolved"
    ]
    normalized_day_city = normalize_place_text(day.city)
    for place in resolved_places:
        if normalize_place_text(place.city) == normalized_day_city:
            return place
    return resolved_places[0] if resolved_places else None


def weather_deduplication_key(place: ResolvedPlace) -> str:
    """Prefer reliable locality identity, then stable rounded coordinates."""

    city = normalize_place_text(place.city)
    country = normalize_place_text(place.country)
    if city and country:
        return f"locality|{city}|{country}"
    return f"coordinates|{place.latitude:.4f}|{place.longitude:.4f}"


def has_weather_eligible_days(trip_plan: TripPlan) -> bool:
    """Return whether any dated day has a trusted representative location."""

    return any(
        day.date is not None and select_representative_place(day) is not None
        for day in trip_plan.days
    )
