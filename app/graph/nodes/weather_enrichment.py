from inspect import isawaitable
from time import perf_counter

from langchain_core.runnables import RunnableConfig

from app.config import get_settings
from app.core.logging import get_logger
from app.graph.state import TravelState
from app.models import TripPlan
from app.services.weather import OpenWeatherProvider, WeatherProvider
from app.services.weather_enrichment import (
    enrich_trip_weather,
    has_weather_eligible_days,
)

logger = get_logger(__name__)


async def weather_enrichment_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, TripPlan | None]:
    """Add optional OpenWeather data without blocking itinerary generation."""

    del config
    started_at = perf_counter()
    itinerary = state.get("itinerary")
    if itinerary is None:
        return {"itinerary": None}
    if not has_weather_eligible_days(itinerary):
        return {"itinerary": itinerary}

    api_key = get_settings().OPENWEATHER_API_KEY
    if not api_key or not api_key.strip():
        logger.warning("weather_enrichment_skipped reason=missing_api_key")
        return {"itinerary": itinerary}

    provider: WeatherProvider | None = None
    try:
        provider = build_weather_provider(api_key)
        enriched = await enrich_trip_weather(itinerary, provider)
    except Exception as exc:
        logger.warning(
            "weather_provider_unavailable scope=trip error_type=%s",
            type(exc).__name__,
        )
        enriched = itinerary
    finally:
        if provider is not None:
            try:
                await _close_provider(provider)
            except Exception as exc:
                logger.warning(
                    "weather_provider_unavailable scope=close error_type=%s",
                    type(exc).__name__,
                )

    logger.info(
        "weather_enrichment_node exited duration=%.4fs",
        perf_counter() - started_at,
    )
    return {"itinerary": enriched}


def build_weather_provider(api_key: str) -> WeatherProvider:
    """Construct the server-side OpenWeather provider."""

    return OpenWeatherProvider(api_key)


async def _close_provider(provider: WeatherProvider) -> None:
    close = getattr(provider, "aclose", None)
    if close is None:
        return
    result = close()
    if isawaitable(result):
        await result
