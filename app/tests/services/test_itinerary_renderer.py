from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    ItineraryDay,
    ResolvedPlace,
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


def test_renderer_shows_provider_address_without_internal_metadata():
    plan = TripPlan(
        title="Ayutthaya Highlights",
        destination="Thailand",
        duration_days=1,
        travelers=1,
        preferences=[],
        days=[
            ItineraryDay(
                day_number=1,
                city="Ayutthaya",
                activities=[
                    Activity(
                        name="Wat Mahathat",
                        category="history",
                        place=ResolvedPlace(
                            provider="geoapify",
                            provider_place_id="place-secret-id",
                            name="Wat Mahathat",
                            formatted_address="Ayutthaya, Thailand",
                            latitude=14.3569,
                            longitude=100.5683,
                            confidence=0.98,
                            resolution_status="resolved",
                        ),
                        place_resolution_status="resolved",
                    )
                ],
            )
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Activities", amount_usd=10)],
            estimated_total_usd=10,
        ),
        practical_notes=[],
    )

    rendered = render_itinerary(plan)

    assert "Address: Ayutthaya, Thailand" in rendered
    assert "place-secret-id" not in rendered
    assert "0.98" not in rendered


def test_renderer_keeps_unresolved_activity_usable():
    plan = TripPlan(
        title="Thailand Plan",
        destination="Thailand",
        duration_days=1,
        travelers=1,
        preferences=[],
        days=[
            ItineraryDay(
                day_number=1,
                city="Bangkok",
                activities=[
                    Activity(
                        name="Hidden Market",
                        category="shopping",
                        location_hint="Bangkok, Thailand",
                    )
                ],
            )
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Shopping", amount_usd=10)],
            estimated_total_usd=10,
        ),
        practical_notes=[],
    )

    rendered = render_itinerary(plan)

    assert "**Hidden Market**" in rendered
    assert "Location: Bangkok, Thailand" in rendered
