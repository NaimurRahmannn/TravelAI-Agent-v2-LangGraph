import asyncio
from datetime import UTC, date, datetime, timedelta

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
    TripPlan,
)
from app.schemas.api import ChatRequest, ChatResponse
from app.services.graph_services import GraphService


def _plan() -> TripPlan:
    return TripPlan(
        title="Thailand Plan",
        origin="Dhaka",
        destination="Thailand",
        duration_days=1,
        travelers=1,
        summary=None,
        preferences=[],
        days=[
            ItineraryDay(
                day_number=1,
                city="Bangkok",
                activities=[Activity(name="Wat Arun", category="culture")],
            )
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Activities", amount_usd=50)],
            estimated_total_usd=50,
            user_budget_usd=100,
        ),
        practical_notes=[],
    )


def test_chat_response_schema_supports_optional_itinerary():
    response = ChatResponse(response="Question?", thread_id="thread-1")

    assert response.itinerary is None
    assert response.model_dump(mode="json")["itinerary"] is None
    assert response.missing_fields == []


def test_chat_request_rejects_end_date_before_start_date():
    start_date = date.today() + timedelta(days=5)

    with pytest.raises(ValidationError, match="End date cannot be before start date"):
        ChatRequest(
            message="Selected dates",
            start_date=start_date,
            end_date=start_date - timedelta(days=1),
        )


def test_chat_request_rejects_past_start_date():
    with pytest.raises(ValidationError, match="Start date cannot be in the past"):
        ChatRequest(
            message="Selected dates",
            start_date=date.today() - timedelta(days=1),
            end_date=date.today(),
        )


def test_chat_request_rejects_partial_or_non_iso_date_selection():
    with pytest.raises(ValidationError, match="Both start_date and end_date"):
        ChatRequest(
            message="Selected dates",
            start_date=date.today() + timedelta(days=1),
        )

    with pytest.raises(ValidationError, match="YYYY-MM-DD"):
        ChatRequest(
            message="Selected dates",
            start_date="09/10/2026",
            end_date="09/14/2026",
        )


def test_chat_request_rejects_unreasonably_long_trip():
    start_date = date.today() + timedelta(days=1)

    with pytest.raises(ValidationError, match="cannot exceed 365 days"):
        ChatRequest(
            message="Selected dates",
            start_date=start_date,
            end_date=start_date + timedelta(days=365),
        )


def test_graph_service_returns_structured_itinerary(monkeypatch):
    plan = _plan()

    class FakeGraph:
        async def aget_state(self, config):
            return None

        async def ainvoke(self, graph_input, *, config):
            return {
                "response": "# Thailand Plan",
                "itinerary": plan,
                "missing_fields": [],
            }

    async def get_fake_graph():
        return FakeGraph()

    monkeypatch.setattr(GraphService, "_get_graph", staticmethod(get_fake_graph))

    response = asyncio.run(
        GraphService().ainvoke(ChatRequest(message="Plan Thailand", thread_id="t-1"))
    )

    assert response.response == "# Thailand Plan"
    assert response.thread_id == "t-1"
    assert response.itinerary == plan


def test_date_update_keeps_thread_and_uses_structured_date_fields(monkeypatch):
    plan = _plan()
    captured = {}
    start_date = date.today() + timedelta(days=10)
    end_date = start_date + timedelta(days=3)

    class FakeGraph:
        async def aget_state(self, config):
            return None

        async def ainvoke(self, graph_input, *, config):
            captured["input"] = graph_input
            captured["config"] = config
            return {
                "response": "# Updated Thailand Plan",
                "itinerary": plan,
                "missing_fields": [],
            }

    async def get_fake_graph():
        return FakeGraph()

    monkeypatch.setattr(GraphService, "_get_graph", staticmethod(get_fake_graph))

    response = asyncio.run(
        GraphService().ainvoke(
            ChatRequest(
                message="I changed my exact travel dates.",
                thread_id="existing-thread",
                start_date=start_date,
                end_date=end_date,
            )
        )
    )

    assert response.thread_id == "existing-thread"
    assert captured["config"]["configurable"]["thread_id"] == "existing-thread"
    assert captured["input"]["selected_start_date"] == start_date
    assert captured["input"]["selected_end_date"] == end_date


def test_chat_response_serializes_nested_place_without_backend_secret():
    plan = _plan()
    data = plan.model_dump()
    forecast_date = date.today() + timedelta(days=2)
    data["days"][0].update(
        {
            "date": forecast_date,
            "weather": DailyWeather(
                provider="openweather",
                date=forecast_date,
                condition="Clouds",
                min_temperature_c=25,
                max_temperature_c=31,
                fetched_at=datetime.now(UTC),
            ).model_dump(),
            "weather_status": "resolved",
        }
    )
    data["days"][0]["activities"][0].update(
        {
            "place": ResolvedPlace(
                provider="geoapify",
                provider_place_id="geo-place-1",
                name="Wat Arun",
                latitude=13.7437,
                longitude=100.4889,
                resolution_status="resolved",
            ).model_dump(),
            "place_resolution_status": "resolved",
            "image": PlaceImage(
                provider="wikimedia_commons",
                wikidata_entity_id="Q5948",
                commons_file_title="File:Wat Arun.jpg",
                original_url="https://upload.wikimedia.org/wat-arun.jpg",
                thumbnail_url="https://upload.wikimedia.org/800px-wat-arun.jpg",
                source_page_url="https://commons.wikimedia.org/wiki/File:Wat_Arun.jpg",
                author="Jane Doe",
                license_short_name="CC BY 4.0",
                attribution_text="Jane Doe / CC BY 4.0 / Wikimedia Commons",
            ).model_dump(),
        }
    )
    response = ChatResponse(
        response="# Thailand Plan",
        thread_id="thread-1",
        itinerary=TripPlan.model_validate(data),
    )

    serialized = response.model_dump_json()

    assert '\"provider_place_id\":\"geo-place-1\"' in serialized
    assert '\"latitude\":13.7437' in serialized
    assert "wikidata_entity_id" in serialized
    assert "wikimedia_commons" in serialized
    assert '"provider":"openweather"' in serialized
    assert '"weather_status":"resolved"' in serialized
    assert "GEOAPIFY_API_KEY" not in serialized
    assert "OPENWEATHER_API_KEY" not in serialized
    assert "WIKIMEDIA_USER_AGENT" not in serialized
    assert "test-geo-key" not in serialized
