from datetime import date as CalendarDate, datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.models.recommendations import TravelRecommendations

PlaceResolutionStatus = Literal[
    "resolved",
    "partially_resolved",
    "unresolved",
]
WeatherStatus = Literal[
    "resolved",
    "outside_forecast_horizon",
    "unavailable",
    "skipped",
]
TravelMode = Literal["walk", "drive", "transit", "bicycle"]
TravelLegStatus = Literal["resolved", "unavailable"]
NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class PlaceImage(BaseModel):
    """Attribution-ready image metadata from Wikimedia Commons."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["wikimedia_commons"]
    wikidata_entity_id: str | None = None
    commons_file_title: NonEmptyString
    original_url: str
    thumbnail_url: str | None = None
    source_page_url: str
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    author: str | None = None
    credit: str | None = None
    license_short_name: NonEmptyString
    license_url: str | None = None
    usage_terms: str | None = None
    attribution_text: NonEmptyString
    description: str | None = None

    @field_validator(
        "original_url",
        "thumbnail_url",
        "source_page_url",
        "license_url",
        mode="before",
    )
    @classmethod
    def validate_http_url(cls, value: object) -> object:
        """Keep serialized URLs as strings while allowing only HTTP(S)."""

        if value is None:
            return value
        if not isinstance(value, str):
            raise ValueError("Image metadata URLs must be strings")
        normalized = value.strip()
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Image metadata URLs must use HTTP(S)")
        return normalized


class ResolvedPlace(BaseModel):
    """Provider-backed identity and coordinates for a planned activity."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["geoapify"]
    provider_place_id: str = Field(min_length=1)
    wikidata_entity_id: str | None = Field(
        default=None,
        pattern=r"^Q[1-9][0-9]*$",
    )
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


class DailyWeather(BaseModel):
    """Provider-authoritative daily forecast derived from 3-hour entries."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["openweather"]
    date: CalendarDate
    condition: NonEmptyString
    description: str | None = None
    min_temperature_c: float
    max_temperature_c: float
    precipitation_probability_pct: float | None = Field(default=None, ge=0, le=100)
    wind_speed_mps: float | None = Field(default=None, ge=0)
    fetched_at: datetime

    @model_validator(mode="after")
    def validate_temperature_range(self) -> "DailyWeather":
        if self.max_temperature_c < self.min_temperature_c:
            raise ValueError("Maximum temperature cannot be below minimum temperature")
        return self


class TravelLeg(BaseModel):
    """Provider-authoritative travel estimate between adjacent activities."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["geoapify"]
    from_activity_index: int = Field(ge=0)
    to_activity_index: int = Field(ge=0)
    from_name: NonEmptyString
    to_name: NonEmptyString
    mode: TravelMode
    distance_meters: float | None = Field(default=None, ge=0)
    duration_seconds: int | None = Field(default=None, ge=0)
    status: TravelLegStatus

    @model_validator(mode="after")
    def validate_leg_status(self) -> "TravelLeg":
        if self.to_activity_index != self.from_activity_index + 1:
            raise ValueError("Travel legs must connect adjacent activities")
        metrics = (self.distance_meters, self.duration_seconds)
        if self.status == "resolved" and any(value is None for value in metrics):
            raise ValueError("Resolved travel legs require distance and duration")
        if self.status == "unavailable" and any(value is not None for value in metrics):
            raise ValueError("Unavailable travel legs cannot include route metrics")
        return self


class Activity(BaseModel):
    """A planned activity with optional provider-backed place enrichment."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    place_search_name: str | None = Field(default=None, min_length=1)
    category: str = Field(min_length=1)
    location_hint: str | None = None
    description: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    reason_for_recommendation: str | None = None
    travel_mode_to_next: TravelMode | None = None
    place: ResolvedPlace | None = None
    place_resolution_status: PlaceResolutionStatus = "unresolved"
    image: PlaceImage | None = None

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
        if self.image is not None and (
            self.place is None or self.place.resolution_status != "resolved"
        ):
            raise ValueError("An image requires a fully resolved provider-backed place")
        return self


class ItineraryDay(BaseModel):
    """One numbered day in a structured itinerary."""

    model_config = ConfigDict(extra="forbid")

    day_number: int = Field(ge=1)
    date: CalendarDate | None = None
    city: str = Field(min_length=1)
    activities: list[Activity] = Field(min_length=1, max_length=3)
    travel_legs: list[TravelLeg] = Field(default_factory=list)
    estimated_daily_cost_usd: float | None = Field(default=None, ge=0)
    weather: DailyWeather | None = None
    weather_status: WeatherStatus = "skipped"

    @model_validator(mode="after")
    def validate_weather_status(self) -> "ItineraryDay":
        if self.weather is None and self.weather_status == "resolved":
            raise ValueError("Resolved weather status requires trusted weather data")
        if self.weather is not None and self.weather_status != "resolved":
            raise ValueError("Trusted weather data requires resolved status")
        if self.weather is not None and self.date != self.weather.date:
            raise ValueError("Weather date must match the itinerary day date")
        seen_from_indices: set[int] = set()
        for leg in self.travel_legs:
            if leg.to_activity_index >= len(self.activities):
                raise ValueError("Travel leg activity index is out of range")
            if leg.from_activity_index in seen_from_indices:
                raise ValueError("Travel legs cannot duplicate an activity pair")
            seen_from_indices.add(leg.from_activity_index)
            from_activity = self.activities[leg.from_activity_index]
            to_activity = self.activities[leg.to_activity_index]
            if leg.from_name != from_activity.name or leg.to_name != to_activity.name:
                raise ValueError("Travel leg names must match their activities")
        return self


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
    start_date: CalendarDate | None = None
    end_date: CalendarDate | None = None
    duration_days: int = Field(ge=1)
    travelers: int = Field(ge=1)
    summary: str | None = None
    preferences: list[str]
    days: list[ItineraryDay] = Field(min_length=1)
    budget: BudgetBreakdown
    recommendations: TravelRecommendations | None = None
    practical_notes: list[str]
