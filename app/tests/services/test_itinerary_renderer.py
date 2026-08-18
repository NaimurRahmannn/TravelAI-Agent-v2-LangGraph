from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    ItineraryDay,
    TripPlan,
)
from app.services.itinerary_renderer import render_itinerary


def test_renderer_outputs_structured_plan_deterministically():
    plan = TripPlan(
        title="Thailand Highlights",
        origin="Dhaka",
        destination="Thailand",
        duration_days=1,
        travelers=2,
        summary="Culture and history in Bangkok.",
        preferences=["culture"],
        days=[
            ItineraryDay(
                day_number=1,
                city="Bangkok",
                activities=[
                    Activity(
                        name="Grand Palace",
                        category="culture",
                        description="Explore the royal complex.",
                    )
                ],
                estimated_daily_cost_usd=80,
            )
        ],
        budget=BudgetBreakdown(
            items=[
                BudgetItem(category="Accommodation", amount_usd=100),
                BudgetItem(category="Activities", amount_usd=80),
            ],
            estimated_total_usd=0,
            user_budget_usd=200,
            international_travel_included=False,
        ),
        practical_notes=["Carry some Thai baht."],
    )

    rendered = render_itinerary(plan)

    assert rendered.startswith("# Thailand Highlights")
    assert "## Day 1 — Bangkok" in rendered
    assert "**Grand Palace**" in rendered
    assert "**Listed activity costs:** $80" in rendered
    assert "- Accommodation: $100" in rendered
    assert "**Estimated total:** $180" in rendered
    assert "**Budget status:** Within budget" in rendered
    assert "**Traveler budget (total for 2 travelers):** $200" in rendered
    assert "**International travel:** Not included" in rendered
    assert "- Carry some Thai baht." in rendered
