from datetime import UTC, date, datetime, timedelta

from app.models import FlightOption, FlightSegment, FlightSlice, HotelOption
from app.services.recommendations import (
    build_recommendation_status,
    rank_flights,
    rank_hotels,
)

FETCHED_AT = datetime(2026, 8, 20, 8, tzinfo=UTC)


def _flight(
    offer_id: str,
    *,
    price: float,
    duration: int,
    stops: int,
) -> FlightOption:
    departure = datetime(2026, 9, 10, 2, tzinfo=UTC)
    arrival = departure + timedelta(minutes=duration)
    return FlightOption(
        provider="swoop",
        provider_offer_id=offer_id,
        origin_code="DAC",
        destination_code="BKK",
        adults=2,
        total_duration_minutes=duration,
        stops=stops,
        total_price=price,
        currency="USD",
        price_type="shopping_total",
        airline_names=["Example Airways"],
        slices=[
            FlightSlice(
                origin_code="DAC",
                destination_code="BKK",
                departure_at=departure,
                arrival_at=arrival,
                duration_minutes=duration,
                stops=stops,
                segments=[
                    FlightSegment(
                        origin_code="DAC",
                        destination_code="BKK",
                        departure_at=departure,
                        arrival_at=arrival,
                        duration_minutes=duration,
                    )
                ],
            )
        ],
        fetched_at=FETCHED_AT,
    )


def _hotel(hotel_id: str, *, price: float, rating: float | None) -> HotelOption:
    return HotelOption(
        provider="future-hotel-provider",
        provider_hotel_id=hotel_id,
        provider_offer_id=f"offer-{hotel_id}",
        name=f"Hotel {hotel_id}",
        check_in=date(2026, 9, 10),
        check_out=date(2026, 9, 14),
        nights=4,
        total_price=price,
        currency="USD",
        rating=rating,
        fetched_at=FETCHED_AT,
    )


def test_ranking_is_deterministic_with_stable_tie_breakers():
    flights = [
        _flight("b", price=500, duration=200, stops=1),
        _flight("c", price=450, duration=300, stops=0),
        _flight("a", price=500, duration=200, stops=1),
    ]
    hotels = [
        _hotel("b", price=300, rating=4.5),
        _hotel("c", price=250, rating=3.0),
        _hotel("a", price=300, rating=4.5),
        _hotel("unrated", price=300, rating=None),
    ]

    assert [item.provider_offer_id for item in rank_flights(flights)] == [
        "c",
        "a",
        "b",
    ]
    assert [item.provider_hotel_id for item in rank_hotels(hotels)] == [
        "c",
        "a",
        "b",
        "unrated",
    ]


def test_status_distinguishes_all_search_outcomes():
    assert build_recommendation_status(searched=False).status == "not_searched"
    assert build_recommendation_status(provider_available=False).status == "unavailable"
    assert build_recommendation_status(provider_result_count=0).status == "no_results"

    available = build_recommendation_status(provider_result_count=20)

    assert available.status == "available"
    assert available.provider_result_count == 20
