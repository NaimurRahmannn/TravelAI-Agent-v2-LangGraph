from dataclasses import dataclass
from typing import Protocol

from app.models.itinerary import TravelMode


@dataclass(frozen=True)
class RouteResult:
    """Normalized routing metrics returned by a provider."""

    distance_meters: float
    duration_seconds: int


class RoutingProviderError(RuntimeError):
    """Base error for a rejected or malformed routing response."""


class RoutingProviderUnavailableError(RoutingProviderError):
    """A provider-wide problem for which more trip requests should stop."""


class RoutingAuthenticationError(RoutingProviderUnavailableError):
    """The configured routing credential was rejected."""


class RoutingRateLimitError(RoutingProviderUnavailableError):
    """The routing provider rate limit remained active after retries."""


class RoutingProvider(Protocol):
    async def get_route(
        self,
        *,
        origin_latitude: float,
        origin_longitude: float,
        destination_latitude: float,
        destination_longitude: float,
        mode: TravelMode,
    ) -> RouteResult | None:
        """Return route metrics, or None when no route exists."""
