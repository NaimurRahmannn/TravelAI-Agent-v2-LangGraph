"""Live currency conversion via the Frankfurter exchange-rate API. """

from time import monotonic
from typing import Optional

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

_FRANKFURTER_RATE_URL = "https://api.frankfurter.dev/v2/rate"
_REQUEST_TIMEOUT_SECONDS = 4.0
_CACHE_TTL_SECONDS = 6 * 60 * 60  # rates refresh ~once/day upstream

_rate_cache: dict[str, tuple[float, float]] = {}  # currency_code -> (rate, cached_at)


def get_usd_conversion_rate(currency_code: str) -> Optional[float]:
    """Return the exchange rate from `currency_code` to USD, or None on failure."""

    code = currency_code.strip().upper()
    if code == "USD":
        return 1.0

    cached = _rate_cache.get(code)
    if cached is not None and monotonic() - cached[1] < _CACHE_TTL_SECONDS:
        return cached[0]

    try:
        response = httpx.get(
            f"{_FRANKFURTER_RATE_URL}/{code}/USD",
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        rate = float(response.json()["rate"])
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        logger.warning("currency conversion lookup failed currency=%s error=%s", code, exc)
        return None

    _rate_cache[code] = (rate, monotonic())
    return rate


def convert_to_usd(amount: float, currency_code: str) -> Optional[float]:
    """Convert `amount` in `currency_code` to USD, or None if the rate is unavailable."""

    rate = get_usd_conversion_rate(currency_code)
    if rate is None:
        return None

    return round(amount * rate, 2)