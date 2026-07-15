from time import perf_counter

from langchain_core.runnables import RunnableConfig

from app.core.logging import get_logger
from app.graph.subgraphs.research_state import ResearchState

logger = get_logger(__name__)

_CLIMATE_PROFILES: dict[str, str] = {
    "japan": (
        "Japan has four distinct seasons: cold winters (0-10C), mild springs "
        "and autumns (10-20C) with cherry blossoms or fall colors, and hot, "
        "humid summers (25-35C) with a rainy season in June-July."
    ),
    "thailand": (
        "Thailand is tropical year-round: a hot season (March-May, often "
        "30-38C), a rainy monsoon season (June-October, humid with frequent "
        "downpours), and a cooler, drier season (November-February, roughly "
        "20-32C) that's generally the most comfortable time to visit."
    ),
    "singapore": (
        "Singapore is tropical and fairly consistent year-round, typically "
        "25-33C with high humidity and the chance of a sudden downpour any "
        "day of the year."
    ),
    "india": (
        "India's climate varies sharply by region and season: hot pre-monsoon "
        "months (March-June, often 30-45C depending on region), a monsoon "
        "season (June-September) with heavy rain in most areas, and a cooler, "
        "drier winter (November-February) that's often the most comfortable."
    ),
    "united kingdom": (
        "The UK has a mild, changeable climate year-round, typically 5-15C in "
        "winter and 15-25C in summer, with rain possible in any season."
    ),
    "uk": (
        "The UK has a mild, changeable climate year-round, typically 5-15C in "
        "winter and 15-25C in summer, with rain possible in any season."
    ),
}

_DEFAULT_CLIMATE_NOTE = (
    "specific seasonal weather data isn't available here — check a live "
    "forecast for your travel dates closer to departure, and pack layers "
    "as a safe default."
)


def weather_worker(
    state: ResearchState,
    config: RunnableConfig,
) -> dict[str, dict[str, str]]:
    """Research likely weather for the extracted destination."""

    started_at = perf_counter()
    trip = state["trip"]
    destination = trip.destination if trip and trip.destination else "the destination"
    logger.info("ResearchGraph.Worker.weather entered destination=%s", destination)

    climate_note = _CLIMATE_PROFILES.get(destination.lower(), _DEFAULT_CLIMATE_NOTE)
    result = f"Weather in {destination}: {climate_note}"

    duration = perf_counter() - started_at
    logger.info(
        "ResearchGraph.Worker.weather exited destination=%s duration=%.4fs",
        destination,
        duration,
    )
    return {
        "research_results": {
            "weather": result,
        },
    }