from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.itinerary import TravelMode

EstimateSource = Literal[
    "geoapify",
    "llm_estimate",
    "planning_policy",
    "unavailable",
]
TimetableStopType = Literal[
    "airport",
    "hotel",
    "activity",
    "planning_buffer",
]
TimetableStopSource = Literal[
    "selected_flight",
    "selected_hotel",
    "itinerary",
    "llm_estimate",
    "planning_policy",
]


class RouteTimeEstimate(BaseModel):
    """Provider fact, planning range, policy duration, or unavailable timing."""

    model_config = ConfigDict(extra="forbid")

    min_minutes: int | None = Field(default=None, ge=1, le=360)
    max_minutes: int | None = Field(default=None, ge=1, le=360)
    planning_minutes: int | None = Field(default=None, ge=1, le=360)
    source: EstimateSource
    approximate: bool = False

    @model_validator(mode="after")
    def validate_range(self) -> "RouteTimeEstimate":
        values = (self.min_minutes, self.max_minutes, self.planning_minutes)
        if self.source == "unavailable":
            if any(value is not None for value in values):
                raise ValueError("Unavailable route timing cannot include minutes")
            if not self.approximate:
                return self
            raise ValueError("Unavailable route timing is not an approximation")
        if any(value is None for value in values):
            raise ValueError("Available route timing requires all minute values")
        assert self.min_minutes is not None
        assert self.max_minutes is not None
        assert self.planning_minutes is not None
        if self.max_minutes < self.min_minutes:
            raise ValueError("Route maximum must not be below minimum")
        if not self.min_minutes <= self.planning_minutes <= self.max_minutes:
            raise ValueError("Planning minutes must fall within the route range")
        if self.source == "geoapify" and (
            self.min_minutes != self.max_minutes
            or self.planning_minutes != self.max_minutes
            or self.approximate
        ):
            raise ValueError("Geoapify timing must remain an exact provider fact")
        if self.source == "llm_estimate" and not self.approximate:
            raise ValueError("LLM route timing must be marked approximate")
        return self


class DetailedRouteLeg(BaseModel):
    """One door-to-door route leg used by the execution timetable."""

    model_config = ConfigDict(extra="forbid")

    leg_id: str = Field(min_length=1)
    origin_stop_id: str = Field(min_length=1)
    destination_stop_id: str = Field(min_length=1)
    origin_name: str = Field(min_length=1)
    destination_name: str = Field(min_length=1)
    requested_mode: TravelMode
    resolved_mode: TravelMode | None = None
    distance_km: float | None = Field(default=None, ge=0)
    duration: RouteTimeEstimate
    provider: Literal["geoapify"] | None = None
    departure_time: datetime | None = None
    arrival_time: datetime | None = None
    note: str | None = None

    @model_validator(mode="after")
    def validate_provider_source(self) -> "DetailedRouteLeg":
        if (
            self.departure_time is not None
            and self.arrival_time is not None
            and self.arrival_time < self.departure_time
        ):
            raise ValueError("Route arrival cannot be before departure")
        if self.duration.source == "geoapify":
            if self.provider != "geoapify" or self.resolved_mode is None:
                raise ValueError("Provider route facts require Geoapify metadata")
        elif self.provider is not None or self.distance_km is not None:
            raise ValueError("Estimated routes cannot expose provider route facts")
        return self


class TimetableStop(BaseModel):
    """One scheduled stop or deterministic planning buffer."""

    model_config = ConfigDict(extra="forbid")

    stop_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    stop_type: TimetableStopType
    arrival_time: datetime | None = None
    departure_time: datetime | None = None
    planned_visit_minutes: int | None = Field(default=None, ge=1, le=360)
    visit_duration_min_minutes: int | None = Field(default=None, ge=1, le=360)
    visit_duration_max_minutes: int | None = Field(default=None, ge=1, le=360)
    source: TimetableStopSource
    scheduled: bool = True
    note: str | None = None

    @model_validator(mode="after")
    def validate_times_and_visit(self) -> "TimetableStop":
        if (
            self.arrival_time is not None
            and self.departure_time is not None
            and self.departure_time < self.arrival_time
        ):
            raise ValueError("Stop departure cannot be before arrival")
        visit_values = (
            self.planned_visit_minutes,
            self.visit_duration_min_minutes,
            self.visit_duration_max_minutes,
        )
        if self.stop_type == "activity" and self.scheduled:
            if any(value is None for value in visit_values):
                raise ValueError("Scheduled activities require a visit duration")
            assert self.visit_duration_min_minutes is not None
            assert self.visit_duration_max_minutes is not None
            assert self.planned_visit_minutes is not None
            if self.visit_duration_max_minutes < self.visit_duration_min_minutes:
                raise ValueError("Visit maximum must not be below minimum")
            if not (
                self.visit_duration_min_minutes
                <= self.planned_visit_minutes
                <= self.visit_duration_max_minutes
            ):
                raise ValueError("Planned visit must fall within its range")
        return self


class DetailedRoutingDay(BaseModel):
    """One local-calendar day in the detailed execution timetable."""

    model_config = ConfigDict(extra="forbid")

    day_number: int = Field(ge=1)
    date: date
    city: str | None = None
    hotel_name: str | None = None
    stops: list[TimetableStop] = Field(default_factory=list)
    route_legs: list[DetailedRouteLeg] = Field(default_factory=list)
    latest_departure_for_airport: datetime | None = None
    warnings: list[str] = Field(default_factory=list)


class DetailedRoutingPlan(BaseModel):
    """Opt-in provider-enriched timetable derived from confirmed travel choices."""

    model_config = ConfigDict(extra="forbid")

    days: list[DetailedRoutingDay] = Field(min_length=1)
    generated_at: datetime
    has_ai_estimates: bool
    warnings: list[str] = Field(default_factory=list)
