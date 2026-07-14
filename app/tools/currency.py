from langchain_core.tools import tool


@tool
def currency(country: str) -> str:
    """Return mock currency information for a country."""

    currencies = {
        "bangladesh": "Bangladeshi Taka (BDT)",
        "india": "Indian Rupee (INR)",
        "japan": "Japanese Yen (JPY)",
        "united states": "United States Dollar (USD)",
        "usa": "United States Dollar (USD)",
        "united kingdom": "Pound Sterling (GBP)",
        "uk": "Pound Sterling (GBP)",
        "france": "Euro (EUR)",
        "germany": "Euro (EUR)",
        "italy": "Euro (EUR)",
        "spain": "Euro (EUR)",
        "thailand": "Thai Baht (THB)",
        "singapore": "Singapore Dollar (SGD)",
        "malaysia": "Malaysian Ringgit (MYR)",
        "turkey": "Turkish Lira (TRY)",
    }
    normalized_country = country.strip().lower()
    currency_name = currencies.get(normalized_country, "the local currency")

    return f"The currency used in {country.strip().title()} is {currency_name}."
