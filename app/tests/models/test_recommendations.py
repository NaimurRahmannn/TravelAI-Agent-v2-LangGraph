from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.models import (
    FlightOption,
    FlightSegment,
    FlightSlice,
    FlightSearchRequest,
    HotelOption,
    HotelSearchRequest,
    RecommendationDomainState,
    RestaurantRecommendation,
    RestaurantSearchRequest,
    TravelRecommendations,
)

FETCHED_AT = datetime(2026, 8, 20, 8, tzinfo=UTC)


def _flight(**updates) -> FlightOption:
    departure = datetime(2026, 9, 10, 2, tzinfo=UTC)
    arrival = datetime(2026, 9, 10, 6, tzinfo=UTC)
    data = {
        "provider": "swoop",
        "provider_offer_id": "offer-1",
        "origin_code": "DAC",
        "destination_code": "BKK",
        "adults": 2,
        "total_duration_minutes": 240,
        "stops": 0,
        "total_price": 550,
        "currency": "usd",
        "price_type": "shopping_total",
        "airline_names": ["Biman Bangladesh Airlines"],
        "slices": [
            FlightSlice(
                origin_code="DAC",
                destination_code="BKK",
                departure_at=departure,
                arrival_at=arrival,
                duration_minutes=240,
                stops=0,
                segments=[
                    FlightSegment(
                        origin_code="DAC",
                        destination_code="BKK",
                        departure_at=departure,
                        arrival_at=arrival,
                        duration_minutes=240,
                        airline_code="BG",
                        airline_name="Biman Bangladesh Airlines",
                        flight_number="88",
                    )
                ],
            )
        ],
        "fetched_at": FETCHED_AT,
    }
    data.update(updates)
    return FlightOption.model_validate(data)


def _hotel(**updates) -> HotelOption:
    data = {
        "provider": "future-hotel-provider",
        "provider_hotel_id": "hotel-1",
        "name": "Riverside Hotel",
        "city": "Bangkok",
        "country": "Thailand",
        "latitude": 13.75,
        "longitude": 100.5,
        "check_in": date(2026, 9, 10),
        "check_out": date(2026, 9, 14),
        "nights": 4,
        "total_price": 400,
        "currency": "USD",
        "price_per_night": 100,
        "rating": 4.5,
        "review_count": 120,
        "image_url": "https://provider.example/hotels/1.jpg",
        "external_url": "https://provider.example/hotels/1",
        "fetched_at": FETCHED_AT,
    }
    data.update(updates)
    return HotelOption.model_validate(data)


def test_valid_flight_option_normalizes_provider_codes_and_currency():
    flight = _flight(provider=" Swoop ", origin_code="dac")

    assert flight.provider == "swoop"
    assert flight.origin_code == "DAC"
    assert flight.currency == "USD"


def test_valid_hotel_option_preserves_total_stay_price():
    hotel = _hotel()

    assert hotel.nights == 4
    assert hotel.total_price == 400
    assert hotel.price_per_night == 100


def test_valid_restaurant_has_no_exact_price_field():
    restaurant = RestaurantRecommendation(
        provider="geoapify",
        provider_place_id="restaurant-1",
        name="Vegetarian House",
        formatted_address="Bangkok, Thailand",
        latitude=13.75,
        longitude=100.5,
        categories=["catering.restaurant"],
        cuisine=["vegetarian"],
        distance_meters=450,
        price_level="moderate",
    )

    assert restaurant.price_level == "moderate"
    assert "total_price" not in restaurant.model_dump()


@pytest.mark.parametrize(
    ("factory", "updates"),
    [
        (_flight, {"total_price": -1}),
        (_flight, {"total_duration_minutes": 0}),
        (_flight, {"stops": -1}),
        (_flight, {"adults": 0}),
        (_hotel, {"total_price": -1}),
        (_hotel, {"nights": 3}),
        (_hotel, {"check_out": date(2026, 9, 10)}),
    ],
)
def test_invalid_commercial_option_values_are_rejected(factory, updates):
    with pytest.raises(ValidationError):
        factory(**updates)


def test_recommendation_container_defaults_are_independent_and_not_searched():
    first = TravelRecommendations()
    second = TravelRecommendations()
    first.flights.append(_flight())

    assert second.flights == []
    assert first.flight_status.status == "not_searched"
    assert second.hotel_status.status == "not_searched"


def test_recommendation_status_rejects_inconsistent_counts():
    with pytest.raises(ValidationError):
        RecommendationDomainState(
            status="no_results",
            provider_result_count=1,
        )
    with pytest.raises(ValidationError):
        RecommendationDomainState(
            status="available",
            provider_result_count=0,
        )


def test_provider_neutral_search_requests_validate_authoritative_inputs():
    departure = date.today() + timedelta(days=10)
    assert FlightSearchRequest(
        origin="Dhaka",
        destination="Bangkok",
        departure_date=departure,
        return_date=departure + timedelta(days=4),
        adults=2,
    ).adults == 2
    assert HotelSearchRequest(
        destination="Thailand",
        city="Bangkok",
        check_in=departure,
        check_out=departure + timedelta(days=4),
        travelers=2,
    ).travelers == 2
    assert RestaurantSearchRequest(
        day_number=1,
        date=departure,
        city="Bangkok",
        latitude=13.75,
        longitude=100.5,
        preferences=["vegetarian"],
    ).preferences == ["vegetarian"]

    with pytest.raises(ValidationError):
        FlightSearchRequest(
            origin="Dhaka",
            destination="Bangkok",
            departure_date=departure,
            return_date=departure - timedelta(days=1),
            adults=2,
        )
