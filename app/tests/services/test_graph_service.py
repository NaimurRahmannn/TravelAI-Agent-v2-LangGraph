import asyncio

from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    ItineraryDay,
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


def test_graph_service_returns_structured_itinerary(monkeypatch):
    plan = _plan()

    class FakeGraph:
        async def aget_state(self, config):
            return None

        async def ainvoke(self, graph_input, *, config):
            return {"response": "# Thailand Plan", "itinerary": plan}

    async def get_fake_graph():
        return FakeGraph()

    monkeypatch.setattr(GraphService, "_get_graph", staticmethod(get_fake_graph))

    response = asyncio.run(
        GraphService().ainvoke(ChatRequest(message="Plan Thailand", thread_id="t-1"))
    )

    assert response.response == "# Thailand Plan"
    assert response.thread_id == "t-1"
    assert response.itinerary == plan
