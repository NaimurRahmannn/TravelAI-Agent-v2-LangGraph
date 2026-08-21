import asyncio
from datetime import date
from types import SimpleNamespace

from app.graph.nodes import hotel_recommendation
from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    ItineraryDay,
    ResolvedPlace,
    TripPlan,
)
from app.services.places.base import PlaceResolution


def _plan() -> TripPlan:
    return TripPlan(
        title="Tokyo plan",
        origin="Dhaka",
        destination="Japan",
        start_date=date(2026, 9, 10),
        end_date=date(2026, 9, 12),
        duration_days=2,
        travelers=1,
        guest_nationality_country_code="BD",
        preferences=[],
        days=[
            ItineraryDay(
                day_number=1,
                date=date(2026, 9, 10),
                city="Tokyo",
                activities=[Activity(name="Temple", category="culture")],
            )
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Local costs", amount_usd=300)],
            estimated_total_usd=300,
        ),
        practical_notes=[],
    )


def test_missing_liteapi_key_does_not_break_itinerary(monkeypatch):
    monkeypatch.setattr(
        hotel_recommendation,
        "get_settings",
        lambda: SimpleNamespace(LITEAPI_API_KEY=None, GEOAPIFY_API_KEY=None),
    )
    plan = _plan()

    result = asyncio.run(
        hotel_recommendation.hotel_recommendation_node(
            {"itinerary": plan},
            {},
        )
    )

    assert result["itinerary"].budget == plan.budget
    assert result["itinerary"].recommendations.hotel_status.status == "unavailable"


def test_node_without_itinerary_is_a_noop():
    result = asyncio.run(
        hotel_recommendation.hotel_recommendation_node(
            {"itinerary": None},
            {},
        )
    )

    assert result == {"itinerary": None}


def test_node_infers_missing_nationality_from_trip_origin(monkeypatch):
    calls = {"hotel": 0, "geoapify": 0}
    hotel_requests = []

    class FakeHotelProvider:
        def __init__(self, api_key):
            assert api_key == "lite-key"

        async def search_hotels(self, request):
            calls["hotel"] += 1
            hotel_requests.append(request)
            return []

        async def aclose(self):
            return None

    class FakePlacesProvider:
        def __init__(self, api_key):
            assert api_key == "geo-key"

        async def resolve_place(self, **kwargs):
            calls["geoapify"] += 1
            is_origin = kwargs["city"] is None
            return PlaceResolution(
                status="resolved",
                place=ResolvedPlace(
                    provider="geoapify",
                    provider_place_id=(
                        "origin-bangladesh" if is_origin else "stay-tokyo"
                    ),
                    name=kwargs["name"],
                    country_code="BD" if is_origin else "JP",
                    latitude=23.81 if is_origin else 35.68,
                    longitude=90.41 if is_origin else 139.76,
                    resolution_status="resolved",
                ),
            )

        async def aclose(self):
            return None

    monkeypatch.setattr(
        hotel_recommendation,
        "get_settings",
        lambda: SimpleNamespace(
            LITEAPI_API_KEY="lite-key",
            GEOAPIFY_API_KEY="geo-key",
        ),
    )
    monkeypatch.setattr(
        hotel_recommendation,
        "LiteApiHotelProvider",
        FakeHotelProvider,
    )
    monkeypatch.setattr(
        hotel_recommendation,
        "GeoapifyPlacesProvider",
        FakePlacesProvider,
    )
    plan = _plan().model_copy(
        update={
            "origin": "Bangladesh",
            "guest_nationality_country_code": None,
        }
    )

    result = asyncio.run(
        hotel_recommendation.hotel_recommendation_node(
            {"itinerary": plan},
            {},
        )
    )

    assert calls == {"hotel": 1, "geoapify": 2}
    assert hotel_requests[0].guest_nationality_country_code == "BD"
    assert result["itinerary"].guest_nationality_country_code == "BD"
    assert result["itinerary"].recommendations.hotel_status.status == "no_results"


def test_origin_nationality_replaces_existing_checkpoint_value():
    class OriginProvider:
        async def resolve_place(self, **kwargs):
            return PlaceResolution(
                status="resolved",
                place=ResolvedPlace(
                    provider="geoapify",
                    provider_place_id="origin-us",
                    name=kwargs["name"],
                    country_code="US",
                    latitude=38.0,
                    longitude=-97.0,
                    resolution_status="resolved",
                ),
            )

    plan = _plan().model_copy(
        update={
            "origin": "United States",
            "guest_nationality_country_code": "BD",
        }
    )

    result = asyncio.run(
        hotel_recommendation._infer_guest_nationality(
            plan,
            OriginProvider(),
        )
    )

    assert result.guest_nationality_country_code == "US"
