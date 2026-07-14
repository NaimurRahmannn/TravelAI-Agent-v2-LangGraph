from time import perf_counter

from langchain_core.runnables import RunnableConfig

from app.core.logging import get_logger
from app.graph.state import TravelState

logger = get_logger(__name__)


def currency_worker(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, dict[str, str]]:
    """Research currency guidance for the extracted destination."""

    started_at = perf_counter()
    trip = state["trip"]
    destination = trip.destination if trip and trip.destination else "the destination"
    logger.info("currency_worker entered destination=%s", destination)

    currency_map = {
        "japan": "Japanese Yen (JPY)",
        "france": "Euro (EUR)",
        "germany": "Euro (EUR)",
        "italy": "Euro (EUR)",
        "spain": "Euro (EUR)",
        "thailand": "Thai Baht (THB)",
        "singapore": "Singapore Dollar (SGD)",
        "malaysia": "Malaysian Ringgit (MYR)",
        "india": "Indian Rupee (INR)",
        "bangladesh": "Bangladeshi Taka (BDT)",
        "united states": "United States Dollar (USD)",
        "usa": "United States Dollar (USD)",
        "united kingdom": "Pound Sterling (GBP)",
        "uk": "Pound Sterling (GBP)",
    }
    currency = currency_map.get(destination.lower(), "the local currency")
    result = (
        f"Currency for {destination}: travelers should plan around {currency}. "
        "Carry a small amount of cash for transit and local vendors, and use a "
        "card with low foreign transaction fees where accepted."
    )

    duration = perf_counter() - started_at
    logger.info(
        "currency_worker exited destination=%s duration=%.4fs",
        destination,
        duration,
    )
    return {
        "research_results": {
            "currency": result,
        },
    }
