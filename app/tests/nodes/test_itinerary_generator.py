from datetime import date, datetime, timedelta, timezone

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda

from app.graph.nodes import itinerary_generator
from app.graph.nodes.itinerary_generator import (
    ItineraryGenerationOutput,
    _clear_untrusted_place_enrichment,
    _has_priced_round_trip_transfer,
    _normalize_plan_details,
    _reconcile_activity_budget_categories,
)
from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    DailyWeather,
    FlightOption,
    FlightSegment,
    FlightSlice,
    ItineraryDay,
    PlaceImage,
    ResolvedPlace,
    Trip,
    TripPlan,
    TravelRecommendations,
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
        ),
        practical_notes=[
            "Visa: Travelers from Bangladesh may use eVisa or Visa on Arrival."
        ],
    )


def _state() -> dict:
    start_date = date.today() + timedelta(days=10)
    return {
        "trip": Trip(
            origin="Dhaka",
            destination="Thailand",
            start_date=start_date,
            end_date=start_date + timedelta(days=1),
            duration=2,
            budget=1000,
            currency="USD",
            travelers=2,
            guest_nationality_country_code="BD",
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
                lambda prompt: captured.update({"prompt": prompt.to_string()})
                or ItineraryGenerationOutput.model_validate(
                    _plan().model_dump(
                        exclude={"recommendations", "guest_nationality_country_code"}
                    )
                )
            )

    monkeypatch.setattr(
        itinerary_generator,
        "get_gemini_llm",
        lambda: StructuredModel(),
    )

    result = itinerary_generator.itinerary_generator_node(_state(), config={})
    plan = result["itinerary"]

    assert isinstance(plan, TripPlan)
    assert captured["schema"] is ItineraryGenerationOutput
    assert "recommendations" not in captured["schema"].model_json_schema()[
        "properties"
    ]
    assert captured["method"] == "json_schema"
    assert plan.origin == "Dhaka"
    assert plan.destination == "Thailand"
    assert plan.start_date == _state()["trip"].start_date
    assert plan.end_date == _state()["trip"].end_date
    assert [day.date for day in plan.days] == [
        _state()["trip"].start_date,
        _state()["trip"].end_date,
    ]
    assert plan.travelers == 2
    assert plan.guest_nationality_country_code == "BD"
    assert plan.preferences == ["culture"]
    assert plan.budget.user_budget_usd == 1000
    assert all("flight" not in item.category.casefold() for item in plan.budget.items)
    assert any(
        item.category == "Contingency reserve"
        for item in plan.budget.items
    )
    assert any(
        "Flights and accommodation are not included" in note
        for note in plan.practical_notes
    )
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
    assert "Agent planning draft" not in captured["prompt"]
    assert "output exactly `Trip.duration` numbered days" in captured["prompt"]


def test_generator_overwrites_conflicting_llm_day_dates(monkeypatch):
    generated = _plan().model_copy(deep=True)
    generated.days[0].date = date(2099, 1, 1)
    generated.days[1].date = date(2099, 1, 2)
    state = _state()
    state["trip"] = state["trip"].model_copy(update={"duration": 30})

    class StructuredModel:
        def with_structured_output(self, schema, *, method):
            return RunnableLambda(lambda _: generated)

    monkeypatch.setattr(
        itinerary_generator,
        "get_gemini_llm",
        lambda: StructuredModel(),
    )

    plan = itinerary_generator.itinerary_generator_node(state, config={})[
        "itinerary"
    ]

    assert plan is not None
    assert plan.duration_days == 2
    assert [day.date for day in plan.days] == [
        _state()["trip"].start_date,
        _state()["trip"].end_date,
    ]


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
                BudgetItem(category="International Air Transportation", amount_usd=600),
                BudgetItem(category="Accommodation", amount_usd=700),
                BudgetItem(category="Food and Dining", amount_usd=400),
                BudgetItem(category="Activities and Tours", amount_usd=50),
                BudgetItem(category="Contingency", amount_usd=100),
            ],
            estimated_total_usd=1850,
            user_budget_usd=1950,
        ),
        practical_notes=["The budget includes a contingency for incidental expenses."],
    )

    normalized = _normalize_plan_details(plan)
    categories = {item.category: item.amount_usd for item in normalized.budget.items}

    assert categories["Activities and Tours"] == 150
    assert categories["Local Transportation"] == 30
    assert categories["Contingency"] == 100
    assert "International Air Transportation" not in categories
    assert "Accommodation" not in categories
    assert normalized.budget.estimated_total_usd == 680
    assert any(
        "Day 1 includes stops outside Bangkok" in note
        and "Floating Market" in note
        and "without an explicitly priced round-trip transfer" in note
        and "not included in the estimate" in note
        for note in normalized.practical_notes
    )


def test_base_budget_strips_room_costs_but_keeps_ground_transport_and_food():
    plan = TripPlan(
        title="Scoped plan",
        origin="Dhaka",
        destination="Thailand",
        duration_days=1,
        travelers=2,
        preferences=[],
        days=[
            ItineraryDay(
                day_number=1,
                city="Bangkok",
                activities=[
                    Activity(
                        name="Hotel check-in",
                        category="accommodation",
                        estimated_cost_usd=300,
                    ),
                    Activity(
                        name="Taxi from airport to hotel",
                        category="transport",
                        estimated_cost_usd=25,
                    ),
                    Activity(
                        name="Hotel-area restaurant",
                        category="food",
                        estimated_cost_usd=40,
                    ),
                ],
            )
        ],
        budget=BudgetBreakdown(
            items=[
                BudgetItem(category="Round-trip airfare", amount_usd=700),
                BudgetItem(category="Hotel rooms", amount_usd=300),
                BudgetItem(category="Airport transfer", amount_usd=25),
                BudgetItem(category="Taxi to hotel", amount_usd=10),
                BudgetItem(category="Bus to hotel", amount_usd=5),
                BudgetItem(category="Hotel-area restaurant", amount_usd=40),
            ],
            estimated_total_usd=0,
            user_budget_usd=1000,
        ),
        practical_notes=[],
    )

    normalized = _normalize_plan_details(plan)
    categories = {item.category: item.amount_usd for item in normalized.budget.items}

    assert normalized.days[0].activities[0].estimated_cost_usd is None
    assert normalized.days[0].activities[1].estimated_cost_usd == 25
    assert normalized.days[0].activities[2].estimated_cost_usd == 40
    assert "Round-trip airfare" not in categories
    assert "Hotel rooms" not in categories
    assert categories["Airport transfer"] == 25
    assert categories["Taxi to hotel"] == 10
    assert categories["Bus to hotel"] == 5
    assert categories["Hotel-area restaurant"] == 40
    assert normalized.budget.estimated_total_usd == 130


def test_reconciliation_defense_skips_partially_normalized_flight_cost():
    plan_data = TripPlan(
        title="Flight defense",
        destination="Japan",
        duration_days=1,
        travelers=1,
        preferences=[],
        days=[
            ItineraryDay(
                day_number=1,
                city="Tokyo",
                activities=[
                    Activity(
                        name="Domestic flight to Osaka",
                        category="transport",
                    )
                ],
            )
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Food", amount_usd=100)],
            estimated_total_usd=100,
        ),
        practical_notes=[],
    ).model_dump()
    plan_data["days"][0]["activities"][0]["estimated_cost_usd"] = 300

    _reconcile_activity_budget_categories(plan_data)

    assert [item["category"] for item in plan_data["budget"]["items"]] == ["Food"]
    assert all(item["amount_usd"] != 300 for item in plan_data["budget"]["items"])


def test_normalization_excludes_flight_and_hotel_but_reconciles_ground_train():
    plan = TripPlan(
        title="Japan transport",
        destination="Japan",
        duration_days=1,
        travelers=1,
        preferences=[],
        days=[
            ItineraryDay(
                day_number=1,
                city="Tokyo",
                activities=[
                    Activity(
                        name="Domestic flight to Osaka",
                        category="transport",
                        estimated_cost_usd=300,
                    ),
                    Activity(
                        name="Train Tokyo to Kyoto",
                        category="transport",
                        estimated_cost_usd=80,
                    ),
                ],
            )
        ],
        budget=BudgetBreakdown(
            items=[
                BudgetItem(category="Food", amount_usd=300),
                BudgetItem(category="Activities", amount_usd=200),
                BudgetItem(category="Domestic flight", amount_usd=300),
                BudgetItem(category="Hotel", amount_usd=500),
            ],
            estimated_total_usd=1300,
        ),
        practical_notes=[],
    )

    normalized = _normalize_plan_details(plan)
    categories = {item.category: item.amount_usd for item in normalized.budget.items}

    assert normalized.days[0].activities[0].estimated_cost_usd is None
    assert normalized.days[0].activities[1].estimated_cost_usd == 80
    assert categories == {
        "Food": 300,
        "Activities": 200,
        "Local Transportation": 80,
    }
    assert normalized.budget.estimated_total_usd == 580


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


def test_generator_clears_llm_invented_place_enrichment():
    plan_data = _plan().model_dump()
    forecast_date = date(2099, 1, 1)
    plan_data["days"][0].update(
        {
            "date": forecast_date,
            "weather": DailyWeather(
                provider="openweather",
                date=forecast_date,
                condition="Clear",
                min_temperature_c=24,
                max_temperature_c=31,
                fetched_at=datetime.now(timezone.utc),
            ).model_dump(),
            "weather_status": "resolved",
        }
    )
    plan_data["days"][0]["activities"][0].update(
        {
            "place": ResolvedPlace(
                provider="geoapify",
                provider_place_id="invented-id",
                name="Invented Place",
                latitude=1,
                longitude=2,
                resolution_status="resolved",
            ).model_dump(),
            "place_resolution_status": "resolved",
            "image": PlaceImage(
                provider="wikimedia_commons",
                wikidata_entity_id="Q999",
                commons_file_title="File:Fake.jpg",
                original_url="https://fake.example/image.jpg",
                source_page_url="https://fake.example/source",
                author="Fake Author",
                license_short_name="CC BY 4.0",
                attribution_text="Fake Author / CC BY 4.0 / Wikimedia Commons",
            ).model_dump(),
        }
    )

    sanitized = _clear_untrusted_place_enrichment(TripPlan.model_validate(plan_data))

    activity = sanitized.days[0].activities[0]
    assert activity.place is None
    assert activity.place_resolution_status == "unresolved"
    assert activity.image is None
    assert sanitized.days[0].weather is None
    assert sanitized.days[0].weather_status == "skipped"


def test_generator_clears_llm_invented_commercial_recommendations():
    plan_data = _plan().model_dump()
    departure = datetime(2026, 9, 10, 2, tzinfo=timezone.utc)
    arrival = datetime(2026, 9, 10, 6, tzinfo=timezone.utc)
    plan_data["recommendations"] = TravelRecommendations(
        flights=[
            FlightOption(
                provider="swoop",
                provider_offer_id="fake-offer",
                origin_code="DAC",
                destination_code="BKK",
                adults=2,
                total_duration_minutes=240,
                stops=0,
                total_price=1,
                currency="USD",
                price_type="shopping_total",
                airline_names=["Invented Airways"],
                slices=[
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
                                airline_name="Invented Airways",
                            )
                        ],
                    )
                ],
                fetched_at=datetime.now(timezone.utc),
            )
        ],
        flight_status={
            "status": "available",
            "provider_result_count": 1,
        },
    ).model_dump()

    sanitized = _clear_untrusted_place_enrichment(TripPlan.model_validate(plan_data))

    assert sanitized.recommendations is None
