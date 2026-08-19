from langchain_core.tools import BaseTool

from app.tools.currency import currency
from app.tools.visa import visa


def get_tools() -> list[BaseTool]:
    """Return all tools available to the travel agent."""

    return [
        currency,
        visa,
    ]
