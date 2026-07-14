from langchain_core.tools import tool


@tool
def weather(destination: str) -> str:
    """Return mock weather guidance for a travel destination."""

    normalized_destination = destination.strip().title()
    return (
        f"The weather in {normalized_destination} is expected to be warm and "
        "pleasant, with daytime temperatures around 24-29C, light breezes, "
        "and a small chance of brief afternoon showers."
    )
