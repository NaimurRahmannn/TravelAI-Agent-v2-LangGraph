from langchain_core.tools import tool


@tool
def visa(destination: str, nationality: str) -> str:
    """Return mock visa guidance for a destination and nationality."""

    normalized_destination = destination.strip().title()
    normalized_nationality = nationality.strip().title()
    return (
        f"For a {normalized_nationality} traveler visiting "
        f"{normalized_destination}, visa rules depend on passport type, trip "
        "purpose, and length of stay. Check the official embassy or immigration "
        "website before booking, and confirm whether an eVisa, visa on arrival, "
        "or advance visa is required."
    )
