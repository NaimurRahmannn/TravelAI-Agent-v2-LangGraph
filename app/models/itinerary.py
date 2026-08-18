from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


PlaceResolutionStatus = Literal[
    "resolved",
    "partially_resolved",
    "unresolved",
]


class ResolvedPlace(BaseModel):
    """Provider-backed identity and coordinates for a planned activity."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["geoapify"]
    provider_place_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    formatted_address: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    country_code: str | None = None
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    categories: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    resolution_status: Literal["resolved", "partially_resolved"]
    source_attribution: str | None = None


class Activity(BaseModel):
    """A planned activity with optional provider-backed place enrichment."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    location_hint: str | None = None
    description: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    reason_for_recommendation: str | None = None
    place: ResolvedPlace | None = None
    place_resolution_status: PlaceResolutionStatus = "unresolved"

    @model_validator(mode="after")
    def validate_place_status(self) -> "Activity":
        """Keep the activity status consistent with its resolved place."""

        if self.place is None and self.place_resolution_status != "unresolved":
            raise ValueError("A resolved status requires provider-backed place data")
        if (
            self.place is not None
            and self.place_resolution_status != self.place.resolution_status
        ):
            raise ValueError("Activity and place resolution statuses must match")
        return self


class ItineraryDay(BaseModel):
    """One numbered day in a structured itinerary."""

    model_config = ConfigDict(extra="forbid")

    day_number: int = Field(ge=1)
    date: str | None = None
    city: str = Field(min_length=1)
    activities: list[Activity] = Field(min_length=1, max_length=3)
    estimated_daily_cost_usd: float | None = Field(default=None, ge=0)


class BudgetItem(BaseModel):
    """One estimated USD budget category."""

    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=1)
    amount_usd: float = Field(ge=0)
    note: str | None = None


class BudgetBreakdown(BaseModel):
    """Structured budget whose total and status are normalized deterministically."""

    model_config = ConfigDict(extra="forbid")

    items: list[BudgetItem] = Field(min_length=1)
    estimated_total_usd: float = Field(ge=0)
    user_budget_usd: float | None = Field(default=None, ge=0)
    within_budget: bool | None = None
    international_travel_included: bool | None = Field(
        default=None,
        description="Whether travel between the origin and destination is included",
    )

    @model_validator(mode="after")
    def calculate_total_and_status(self) -> "BudgetBreakdown":
        """Replace model-provided arithmetic with deterministic values."""

        total = round(sum(item.amount_usd for item in self.items), 2)
        self.estimated_total_usd = total
        self.within_budget = (
            total <= self.user_budget_usd
            if self.user_budget_usd is not None
            else None
        )
        return self


class TripPlan(BaseModel):
    """Authoritative structured representation of a generated itinerary."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    origin: str | None = None
    destination: str = Field(min_length=1)
    duration_days: int = Field(ge=1)
    travelers: int = Field(ge=1)
    summary: str | None = None
    preferences: list[str]
    days: list[ItineraryDay] = Field(min_length=1)
    budget: BudgetBreakdown
    practical_notes: list[str]
