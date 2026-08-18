from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda

from app.graph.nodes import itinerary_generator
from app.graph.nodes.itinerary_generator import (
    _has_priced_round_trip_transfer,
    _normalize_plan_details,
)
from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    ItineraryDay,
    Trip,
    TripPlan,
)


def _plan() -> TripPlan:
    return TripPlan(
        title="Model title",
        origin="Wrong origin",
        destination="Wrong destination",
        duration_days=2,
        travelers=1,
        summary="A draft summary.",
        preferences=[],
        days=[
            ItineraryDay(
                day_number=1,
                city="Bangkok",
                activities=[
                    Activity(
                        name="Grand Palace",
                        category="culture",
                        estimated_cost_usd=100,
                    )
                ],
            ),
            ItineraryDay(
                day_number=2,
                city="Bangkok",
                activities=[
                    Activity(
                        name="Wat Arun",
                        category="culture",
                        estimated_cost_usd=50,
                    )
                ],
            ),
        ],
        budget=BudgetBreakdown(
            items=[
                BudgetItem(
                    category="International Flights",
                    amount_usd=800,
                    note="Estimated round trip.",
                )
            ],
            estimated_total_usd=800,
            user_budget_usd=9999,
            international_travel_included=True,
        ),
        practical_notes=[
            "Visa: Travelers from Bangladesh may use eVisa or Visa on Arrival."
        ],
    )


def _state() -> dict:
    return {
        "trip": Trip(
            origin="Dhaka",
            destination="Thailand",
            duration=2,
            budget=1000,
            currency="USD",
            travelers=2,
            preferences=["culture"],
        ),
        "messages": [
            HumanMessage(content="Plan a cultural Thailand trip."),
            AIMessage(content="Use Bangkok as the base."),
        ],
        "research_results": {"summary": "Research context"},
        "long_term_memories": ["Traveler prefers vegetarian food."],
    }


def test_generator_stores_plan_and_enforces_authoritative_trip(monkeypatch):
    captured = {}

    class StructuredModel:
        def with_structured_output(self, schema, *, method):
            captured["schema"] = schema
            captured["method"] = method
            return RunnableLambda(
                lambda prompt: captured.update({"prompt": prompt.to_string()}) or _plan()
            )

    monkeypatch.setattr(
        itinerary_generator,
        "get_gemini_llm",
        lambda: StructuredModel(),
    )

    result = itinerary_generator.itinerary_generator_node(_state(), config={})
    plan = result["itinerary"]

    assert isinstance(plan, TripPlan)
    assert captured["schema"] is TripPlan
    assert captured["method"] == "json_schema"
    assert plan.origin == "Dhaka"
    assert plan.destination == "Thailand"
    assert plan.travelers == 2
    assert plan.preferences == ["culture"]
    assert plan.budget.user_budget_usd == 1000
    assert plan.budget.international_travel_included is True
    assert any(
        item.category == "Contingency reserve"
        for item in plan.budget.items
    )
    international_flights = next(
        item
        for item in plan.budget.items
        if item.category == "International Flights"
    )
    assert "Travel class is not specified" in international_flights.note
    assert [day.estimated_daily_cost_usd for day in plan.days] == [100, 50]
    assert all(
        activity.location_hint
        for day in plan.days
        for activity in day.activities
    )
    visa_note = next(note for note in plan.practical_notes if note.startswith("Visa:"))
    assert "actual passport" in visa_note
    assert "eVisa" not in visa_note
    assert "Visa on Arrival" not in visa_note
    assert "Research context" in captured["prompt"]
    assert "Traveler prefers vegetarian food" in captured["prompt"]
    assert "Use Bangkok as the base" in captured["prompt"]


def test_generator_failure_returns_none_for_agent_text_fallback(monkeypatch):
    class FailingModel:
        def with_structured_output(self, schema, *, method):
            def fail(_):
                raise TimeoutError("provider timeout")

            return RunnableLambda(fail)

    monkeypatch.setattr(
        itinerary_generator,
        "get_gemini_llm",
        lambda: FailingModel(),
    )

    assert itinerary_generator.itinerary_generator_node(_state(), config={}) == {
        "itinerary": None
    }


def test_normalization_reconciles_categories_and_flags_cross_city_logistics():
    plan = TripPlan(
        title="Thailand Plan",
        origin="Bangladesh",
        destination="Thailand",
        duration_days=1,
        travelers=2,
        summary=None,
        preferences=[],
        days=[
            ItineraryDay(
                day_number=1,
                city="Bangkok",
                activities=[
                    Activity(
                        name="Grand Palace",
                        category="culture",
                        location_hint="Grand Palace, Bangkok, Thailand",
                        estimated_cost_usd=100,
                    ),
                    Activity(
                        name="Floating Market",
                        category="culture",
                        location_hint="Ratchaburi, Thailand",
                        estimated_cost_usd=50,
                    ),
                    Activity(
                        name="Airport Transfer",
                        category="transport",
                        location_hint="Suvarnabhumi Airport, Bangkok, Thailand",
                        estimated_cost_usd=30,
                    ),
                ],
            )
        ],
        budget=BudgetBreakdown(
            items=[
                BudgetItem(category="International Transportation", amount_usd=600),
                BudgetItem(category="Accommodation", amount_usd=700),
                BudgetItem(category="Food and Dining", amount_usd=400),
                BudgetItem(category="Activities and Tours", amount_usd=50),
                BudgetItem(category="Contingency", amount_usd=100),
            ],
            estimated_total_usd=1850,
            user_budget_usd=1950,
            international_travel_included=True,
        ),
        practical_notes=["The budget includes a contingency for incidental expenses."],
    )

    normalized = _normalize_plan_details(plan)
    categories = {item.category: item.amount_usd for item in normalized.budget.items}

    assert categories["Activities and Tours"] == 150
    assert categories["Local Transportation"] == 30
    assert "Contingency" not in categories
    assert normalized.budget.estimated_total_usd == 1880
    assert normalized.budget.within_budget is True
    assert not any(
        "contingency" in note.casefold()
        for note in normalized.practical_notes
    )
    assert any(
        "Day 1 includes stops outside Bangkok" in note
        and "Floating Market" in note
        and "without an explicitly priced round-trip transfer" in note
        and "not included in the estimate" in note
        for note in normalized.practical_notes
    )


def test_round_trip_transfer_must_include_a_price():
    day = {
        "activities": [
            {
                "name": "Round-trip private transfer",
                "category": "transport",
                "description": "Both ways between Bangkok and Ayutthaya.",
                "estimated_cost_usd": None,
            }
        ]
    }

    assert _has_priced_round_trip_transfer(day) is False

    day["activities"][0]["estimated_cost_usd"] = 120

    assert _has_priced_round_trip_transfer(day) is True
