from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    DailyWeather,
    ItineraryDay,
    PlaceImage,
    ResolvedPlace,
    TravelLeg,
    TripPlan,
)


def _valid_plan() -> TripPlan:
    return TripPlan(
        title="2-Day Kyoto Itinerary",
        origin="Dhaka",
        destination="Japan",
        duration_days=2,
        travelers=2,
        summary="A culture-focused city break.",
        preferences=["culture"],
        days=[
            ItineraryDay(
                day_number=1,
                city="Kyoto",
                activities=[Activity(name="Fushimi Inari", category="culture")],
            ),
            ItineraryDay(
                day_number=2,
                city="Kyoto",
                activities=[Activity(name="Kinkaku-ji", category="history")],
            ),
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Activities", amount_usd=120)],
            estimated_total_usd=999,
            user_budget_usd=200,
        ),
        practical_notes=["Costs are estimates."],
    )


def test_valid_trip_plan_serializes_and_calculates_budget():
    plan = _valid_plan()

    assert plan.budget.estimated_total_usd == 120
    assert "within_budget" not in plan.budget.model_dump()
    assert "international_travel_included" not in plan.budget.model_dump()
    assert plan.model_dump(mode="json")["days"][0]["day_number"] == 1


def test_base_budget_strips_airfare_and_accommodation_and_recomputes_total():
    budget = BudgetBreakdown(
        items=[
            BudgetItem(category="Flights", amount_usd=700),
            BudgetItem(category="Hotel Accommodation", amount_usd=500),
            BudgetItem(category="Food", amount_usd=300),
            BudgetItem(category="Activities", amount_usd=200),
            BudgetItem(category="Local Transportation", amount_usd=100),
        ],
        estimated_total_usd=2000,
        user_budget_usd=2000,
    )

    assert [item.category for item in budget.items] == [
        "Food",
        "Activities",
        "Local Transportation",
    ]
    assert budget.estimated_total_usd == 600
    assert budget.user_budget_usd == 2000


def test_trip_plan_validation_preserves_target_and_recomputes_base_total():
    data = _valid_plan().model_dump()
    data["days"][0]["activities"][0] = {
        "name": "Stay at hotel",
        "category": "lodging",
        "estimated_cost_usd": 500,
    }
    data["budget"] = {
        "items": [
            {"category": "Airfare", "amount_usd": 700},
            {"category": "Hotel room", "amount_usd": 500},
            {"category": "Trip-local costs", "amount_usd": 800},
        ],
        "estimated_total_usd": 2000,
        "user_budget_usd": 2000,
    }

    plan = TripPlan.model_validate(data)

    assert plan.days[0].activities[0].estimated_cost_usd is None
    assert [item.category for item in plan.budget.items] == ["Trip-local costs"]
    assert plan.budget.estimated_total_usd == 800
    assert plan.budget.user_budget_usd == 2000


@pytest.mark.parametrize(
    "category",
    [
        "Airport transfer",
        "Taxi from airport to hotel",
        "Airport shuttle",
        "Bus to hotel",
        "Train to hotel",
        "Local transport",
        "Local transportation",
        "International Transportation",
        "Train Tokyo to Kyoto",
        "Inter-city train",
        "Meals near hotel",
        "Restaurant near hotel",
    ],
)
def test_base_budget_keeps_ground_transport_and_nearby_meals(category):
    budget = BudgetBreakdown(
        items=[BudgetItem(category=category, amount_usd=25)],
        estimated_total_usd=999,
    )

    assert budget.items[0].category == category
    assert budget.estimated_total_usd == 25


@pytest.mark.parametrize(
    "category",
    [
        "Flight",
        "Airfare",
        "Air tickets",
        "Airline ticket",
        "International airfare",
        "Domestic flight",
        "International flight tickets",
        "Hotel",
        "Accommodation",
        "Hotel room",
        "Lodging",
        "Hostel stay",
        "Resort accommodation",
        "Rental accommodation cost",
    ],
)
def test_base_budget_excludes_controlled_airfare_and_room_labels(category):
    budget = BudgetBreakdown(
        items=[
            BudgetItem(category=category, amount_usd=500),
            BudgetItem(category="Food", amount_usd=100),
        ],
        estimated_total_usd=600,
    )

    assert [item.category for item in budget.items] == ["Food"]
    assert budget.estimated_total_usd == 100


def test_lodging_activity_cost_is_cleared_but_taxi_cost_is_retained():
    hotel = Activity(
        name="Hotel check-in",
        category="accommodation",
        estimated_cost_usd=400,
    )
    taxi = Activity(
        name="Taxi to hotel",
        category="transport",
        estimated_cost_usd=25,
    )

    assert hotel.estimated_cost_usd is None
    assert taxi.estimated_cost_usd == 25


@pytest.mark.parametrize(
    ("name", "category"),
    [
        ("Flight to Osaka", "flight"),
        ("Domestic flight to Osaka", "transport"),
        ("International flight", "transport"),
        ("Flight from Tokyo to Sapporo", "logistics"),
        ("Airfare", "expense"),
        ("Air ticket", "expense"),
        ("Air tickets", "expense"),
        ("Flight ticket", "expense"),
        ("Flight tickets", "expense"),
        ("Airline ticket", "expense"),
        ("Airline tickets", "expense"),
        ("Travel to Osaka", "airfare"),
        ("Travel to Osaka", "air travel"),
        ("Travel to Osaka", "air_transport"),
        ("Travel to Osaka", "air transportation"),
    ],
)
def test_explicit_flight_ticket_activity_cost_is_cleared(name, category):
    activity = Activity(
        name=name,
        category=category,
        estimated_cost_usd=300,
    )

    assert activity.estimated_cost_usd is None


@pytest.mark.parametrize(
    ("name", "category", "cost"),
    [
        ("Airport transfer", "transport", 35),
        ("Airport shuttle", "transportation", 20),
        ("Taxi to airport", "transport", 25),
        ("Taxi from airport", "transport", 25),
        ("Bus from airport", "transport", 10),
        ("Airport rail", "transport", 18),
        ("Airport express train", "transport", 18),
        ("Train Tokyo to Kyoto", "transportation", 80),
        ("Local transportation", "transportation", 100),
        ("Inter-city train", "transport", 80),
        ("Taxi from airport to hotel", "transport", 25),
        ("Bus to hotel", "transport", 10),
        ("Train to hotel", "transportation", 20),
    ],
)
def test_ground_transport_activity_cost_is_retained(name, category, cost):
    activity = Activity(
        name=name,
        category=category,
        estimated_cost_usd=cost,
    )

    assert activity.estimated_cost_usd == cost


@pytest.mark.parametrize(
    ("model", "data"),
    [
        (Activity, {"name": "Museum", "category": "history", "estimated_cost_usd": -1}),
        (BudgetItem, {"category": "Food", "amount_usd": -1}),
        (
            ItineraryDay,
            {"day_number": 0, "city": "Kyoto", "activities": [{"name": "A", "category": "B"}]},
        ),
        (ItineraryDay, {"day_number": 1, "city": "Kyoto", "activities": []}),
        (
            ItineraryDay,
            {
                "day_number": 1,
                "city": "Kyoto",
                "activities": [
                    {"name": str(index), "category": "visit"}
                    for index in range(4)
                ],
            },
        ),
    ],
)
def test_invalid_cost_day_and_activity_constraints_are_rejected(model, data):
    with pytest.raises(ValidationError):
        model.model_validate(data)


def test_unknown_fields_are_rejected():
    data = _valid_plan().model_dump()
    data["coordinates"] = [35.0, 135.0]

    with pytest.raises(ValidationError):
        TripPlan.model_validate(data)


def test_resolved_and_unavailable_travel_leg_invariants():
    resolved = TravelLeg(
        provider="geoapify",
        from_activity_index=0,
        to_activity_index=1,
        from_name="Temple",
        to_name="Museum",
        mode="walk",
        distance_meters=850,
        duration_seconds=620,
        status="resolved",
    )

    assert resolved.duration_seconds == 620
    with pytest.raises(ValidationError):
        TravelLeg(
            provider="geoapify",
            from_activity_index=0,
            to_activity_index=2,
            from_name="Temple",
            to_name="Museum",
            mode="walk",
            status="unavailable",
        )
    with pytest.raises(ValidationError):
        TravelLeg(
            provider="geoapify",
            from_activity_index=0,
            to_activity_index=1,
            from_name="Temple",
            to_name="Museum",
            mode="walk",
            distance_meters=850,
            status="unavailable",
        )


def _resolved_place(**updates) -> ResolvedPlace:
    data = {
        "provider": "geoapify",
        "provider_place_id": "place-123",
        "name": "Wat Mahathat",
        "formatted_address": "Ayutthaya, Thailand",
        "city": "Ayutthaya",
        "state": "Phra Nakhon Si Ayutthaya",
        "country": "Thailand",
        "country_code": "th",
        "latitude": 14.3569,
        "longitude": 100.5683,
        "categories": ["tourism.sights"],
        "confidence": 0.98,
        "resolution_status": "resolved",
        "source_attribution": "OpenStreetMap contributors",
    }
    data.update(updates)
    return ResolvedPlace.model_validate(data)


def test_resolved_place_validates_and_serializes():
    place = _resolved_place()

    serialized = place.model_dump(mode="json")

    assert serialized["provider"] == "geoapify"
    assert serialized["latitude"] == 14.3569
    assert serialized["categories"] == ["tourism.sights"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("latitude", 90.01),
        ("latitude", -90.01),
        ("longitude", 180.01),
        ("longitude", -180.01),
        ("confidence", 1.01),
        ("confidence", -0.01),
    ],
)
def test_resolved_place_rejects_invalid_coordinates_and_confidence(field, value):
    with pytest.raises(ValidationError):
        _resolved_place(**{field: value})


def test_resolved_place_rejects_unknown_fields():
    data = _resolved_place().model_dump()
    data["raw_provider_payload"] = {"secret": "value"}

    with pytest.raises(ValidationError):
        ResolvedPlace.model_validate(data)


def _place_image(**updates) -> PlaceImage:
    data = {
        "provider": "wikimedia_commons",
        "wikidata_entity_id": "Q660585",
        "commons_file_title": "File:Wat Mahathat.jpg",
        "original_url": "https://upload.wikimedia.org/wat.jpg",
        "thumbnail_url": "https://upload.wikimedia.org/800px-wat.jpg",
        "source_page_url": "https://commons.wikimedia.org/wiki/File:Wat.jpg",
        "width": 1200,
        "height": 800,
        "author": "Jane Doe",
        "license_short_name": "CC BY-SA 4.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "attribution_text": "Jane Doe / CC BY-SA 4.0 / Wikimedia Commons",
    }
    data.update(updates)
    return PlaceImage.model_validate(data)


def test_place_image_validates_and_serializes():
    serialized = _place_image().model_dump(mode="json")

    assert serialized["provider"] == "wikimedia_commons"
    assert serialized["wikidata_entity_id"] == "Q660585"
    assert serialized["width"] == 1200


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("commons_file_title", "   "),
        ("original_url", "javascript:alert(1)"),
        ("source_page_url", ""),
        ("thumbnail_url", "ftp://example.test/image.jpg"),
        ("width", 0),
        ("height", -1),
        ("license_short_name", " "),
        ("attribution_text", " "),
    ],
)
def test_place_image_rejects_invalid_required_metadata(field, value):
    with pytest.raises(ValidationError):
        _place_image(**{field: value})


def test_place_image_rejects_unknown_fields():
    data = _place_image().model_dump()
    data["raw_wikimedia_payload"] = {"unsafe": True}

    with pytest.raises(ValidationError):
        PlaceImage.model_validate(data)


def test_activity_image_requires_a_fully_resolved_place():
    with pytest.raises(ValidationError):
        Activity(name="Wat Mahathat", category="history", image=_place_image())

    place = _resolved_place()
    activity = Activity(
        name="Wat Mahathat",
        category="history",
        place=place,
        place_resolution_status="resolved",
        image=_place_image(),
    )

    assert activity.image is not None


def _daily_weather(**updates) -> DailyWeather:
    data = {
        "provider": "openweather",
        "date": date(2026, 8, 21),
        "condition": "Rain",
        "description": "light rain",
        "min_temperature_c": 25.2,
        "max_temperature_c": 31.4,
        "precipitation_probability_pct": 70,
        "wind_speed_mps": 4.5,
        "fetched_at": datetime(2026, 8, 19, 12, tzinfo=timezone.utc),
    }
    data.update(updates)
    return DailyWeather.model_validate(data)


def test_daily_weather_validates_and_serializes():
    serialized = _daily_weather().model_dump(mode="json")

    assert serialized["provider"] == "openweather"
    assert serialized["date"] == "2026-08-21"
    assert serialized["precipitation_probability_pct"] == 70


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("precipitation_probability_pct", -1),
        ("precipitation_probability_pct", 101),
        ("wind_speed_mps", -0.1),
        ("max_temperature_c", 20),
    ],
)
def test_daily_weather_rejects_invalid_values(field, value):
    updates = {field: value}
    if field == "max_temperature_c":
        updates["min_temperature_c"] = 21

    with pytest.raises(ValidationError):
        _daily_weather(**updates)


def test_itinerary_day_requires_consistent_weather_status_and_date():
    with pytest.raises(ValidationError, match="requires trusted weather data"):
        ItineraryDay(
            day_number=1,
            date=date(2026, 8, 21),
            city="Bangkok",
            activities=[Activity(name="Wat Arun", category="culture")],
            weather_status="resolved",
        )

    with pytest.raises(ValidationError, match="must match"):
        ItineraryDay(
            day_number=1,
            date=date(2026, 8, 22),
            city="Bangkok",
            activities=[Activity(name="Wat Arun", category="culture")],
            weather=_daily_weather(),
            weather_status="resolved",
        )
