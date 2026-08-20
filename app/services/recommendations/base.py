from typing import Protocol

from app.models import (
    FlightOption,
    FlightSearchRequest,
    HotelOption,
    HotelSearchRequest,
    RestaurantRecommendation,
    RestaurantSearchRequest,
)


class FlightProviderError(RuntimeError):
    """Base error for safe flight-provider failures."""


class FlightProviderUnavailableError(FlightProviderError):
    """A flight provider could not complete the optional search."""


class FlightProvider(Protocol):
    async def search_flights(
        self,
        request: FlightSearchRequest,
    ) -> list[FlightOption]:
        """Return provider facts without applying traveler budget policy."""


class HotelProvider(Protocol):
    async def search_hotels(
        self,
        request: HotelSearchRequest,
    ) -> list[HotelOption]:
        """Return provider facts without applying traveler budget policy."""


class RestaurantProvider(Protocol):
    async def search_restaurants(
        self,
        request: RestaurantSearchRequest,
    ) -> list[RestaurantRecommendation]:
        """Return provider-backed places without inventing exact meal prices."""
