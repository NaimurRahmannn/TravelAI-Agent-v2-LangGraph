from app.models import FlightOption, HotelOption, RecommendationDomainState


def rank_flights(options: list[FlightOption]) -> list[FlightOption]:
    """Return a stable provider-neutral flight ordering."""

    return sorted(
        options,
        key=lambda option: (
            option.total_price,
            option.total_duration_minutes,
            option.stops,
            option.provider,
            option.provider_offer_id,
        ),
    )


def rank_hotels(options: list[HotelOption]) -> list[HotelOption]:
    """Return a stable provider-neutral hotel ordering."""

    return sorted(
        options,
        key=lambda option: (
            option.total_price,
            option.rating is None,
            -(option.rating or 0),
            option.provider,
            option.provider_hotel_id,
        ),
    )


def build_recommendation_status(
    *,
    provider_result_count: int = 0,
    searched: bool = True,
    provider_available: bool = True,
) -> RecommendationDomainState:
    """Distinguish unsearched, unavailable, empty, and successful searches."""

    if not searched:
        return RecommendationDomainState(status="not_searched")
    if not provider_available:
        return RecommendationDomainState(status="unavailable")
    if provider_result_count == 0:
        return RecommendationDomainState(status="no_results")
    return RecommendationDomainState(
        status="available",
        provider_result_count=provider_result_count,
    )
