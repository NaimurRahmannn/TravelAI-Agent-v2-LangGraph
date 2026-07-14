from langchain_core.tools import BaseTool

from app.tools.currency import currency
from app.tools.visa import visa
from app.tools.weather import weather


def get_tools() -> list[BaseTool]:
    """Return all tools available to the travel agent."""

    return [
        weather,
        currency,
        visa,
    ]
