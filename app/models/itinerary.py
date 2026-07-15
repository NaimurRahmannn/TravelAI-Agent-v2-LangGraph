from typing import Optional

from pydantic import BaseModel, Field


class ItineraryDay(BaseModel):
    """A single day in a structured itinerary."""

    day_number: int = Field(description="1-indexed day number")
    title: str = Field(description="Short title, e.g. 'Arrival in Bangkok'")
    activities: list[str] = Field(
        default_factory=list,
        description="1-3 concrete, named activities for this day",
    )


class BudgetBreakdown(BaseModel):
    """Estimated cost breakdown for a trip. Fields are left null if unknown."""

    flights: Optional[float] = None
    accommodation: Optional[float] = None
    transport: Optional[float] = None
    food_and_activities: Optional[float] = None


class Itinerary(BaseModel):
    """A fully structured, day-by-day trip itinerary."""

    destination: str
    duration_days: int
    days: list[ItineraryDay]
    budget_breakdown: BudgetBreakdown
    currency_note: Optional[str] = None
    weather_note: Optional[str] = None
    visa_note: Optional[str] = None