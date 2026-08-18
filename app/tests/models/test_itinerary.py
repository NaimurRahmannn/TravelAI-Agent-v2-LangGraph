import pytest
from pydantic import ValidationError

from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    ItineraryDay,
    ResolvedPlace,
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
    assert plan.budget.within_budget is True
    assert plan.model_dump(mode="json")["days"][0]["day_number"] == 1


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
