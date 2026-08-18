from pydantic import BaseModel, ConfigDict, Field, model_validator


class Activity(BaseModel):
    """A planned activity without external-provider metadata."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    location_hint: str | None = None
    description: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    reason_for_recommendation: str | None = None


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
