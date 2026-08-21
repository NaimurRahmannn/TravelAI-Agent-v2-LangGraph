import re
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
    """Attribution-ready image metadata from a trusted image provider."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["wikimedia_commons", "pexels"]
    provider_image_id: NonEmptyString | None = None
    wikidata_entity_id: str | None = None
    commons_file_title: NonEmptyString | None = None
    original_url: str
    thumbnail_url: str | None = None
    source_page_url: str
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    author: str | None = None
    author_url: str | None = None
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
        "author_url",
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

    @model_validator(mode="after")
    def validate_provider_identity(self) -> "PlaceImage":
        if self.provider == "wikimedia_commons" and not self.commons_file_title:
            raise ValueError("Wikimedia images require a Commons file title")
        if self.provider == "pexels":
            if not self.provider_image_id:
                raise ValueError("Pexels images require a provider image ID")
            if not self.author or not self.author.strip() or not self.author_url:
                raise ValueError("Pexels images require photographer attribution")
        return self


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
    def normalize_trusted_fields(self) -> "Activity":
        """Keep provider state consistent and remove explicit room charges."""

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
        if self.estimated_cost_usd is not None:
            if _is_lodging_room_activity(self.name, self.category):
                self.estimated_cost_usd = None
            elif _is_flight_ticket_activity(self.name, self.category):
                self.estimated_cost_usd = None
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
    """Authoritative base-trip estimate, excluding airfare and lodging rooms."""

    model_config = ConfigDict(extra="forbid")

    items: list[BudgetItem] = Field(min_length=1)
    estimated_total_usd: float = Field(ge=0)
    user_budget_usd: float | None = Field(default=None, ge=0)

    @model_validator(mode="before")
    @classmethod
    def remove_excluded_costs(cls, value: object) -> object:
        """Enforce the base-budget scope before accepting any generated data."""

        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        raw_items = normalized.get("items")
        if not isinstance(raw_items, list):
            return normalized

        included_items = [
            item for item in raw_items if not _is_excluded_budget_item(item)
        ]
        if not included_items:
            included_items = [
                {
                    "category": "Local trip costs",
                    "amount_usd": 0,
                    "note": "No local cost estimate was available for this plan.",
                }
            ]
        normalized["items"] = included_items
        return normalized

    @model_validator(mode="after")
    def calculate_total(self) -> "BudgetBreakdown":
        """Replace model-provided arithmetic with the surviving item total."""

        self.estimated_total_usd = round(
            sum(item.amount_usd for item in self.items),
            2,
        )
        return self


class TripPlan(BaseModel):
    """Itinerary whose budget is the authoritative trip-local base estimate."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    origin: str | None = None
    destination: str = Field(min_length=1)
    start_date: CalendarDate | None = None
    end_date: CalendarDate | None = None
    duration_days: int = Field(ge=1)
    travelers: int = Field(ge=1)
    guest_nationality_country_code: str | None = None
    summary: str | None = None
    preferences: list[str]
    days: list[ItineraryDay] = Field(min_length=1)
    budget: BudgetBreakdown
    recommendations: TravelRecommendations | None = None
    practical_notes: list[str]

    @field_validator("guest_nationality_country_code", mode="before")
    @classmethod
    def normalize_guest_nationality(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Guest nationality must be an ISO-2 country code")
        normalized = value.strip().upper()
        if len(normalized) != 2 or not normalized.isalpha():
            raise ValueError("Guest nationality must be an ISO-2 country code")
        return normalized


def _normalized_cost_label(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


_AIRFARE_LABEL = re.compile(
    r"(?:(?:international|domestic|round trip|return|one way) )*"
    r"(?:flight|flights|airfare|air fare|air ticket|air tickets|"
    r"airline ticket|airline tickets|flight ticket|flight tickets)"
    r"(?: (?:cost|costs|fare|fares))?"
    r"(?: for \d+ (?:adult|adults|traveler|travelers|passenger|passengers))?"
)
_LODGING_CORE_LABELS = {
    "accommodation",
    "accommodations",
    "airbnb",
    "hotel",
    "hotel accommodation",
    "hotel lodging",
    "hotel room",
    "hotel rooms",
    "hotel stay",
    "hotels",
    "hostel",
    "hostel accommodation",
    "hostel lodging",
    "hostel room",
    "hostel rooms",
    "hostel stay",
    "hostels",
    "lodging",
    "rental accommodation",
    "resort",
    "resort accommodation",
    "resort lodging",
    "resort room",
    "resort rooms",
    "resort stay",
    "resorts",
    "vacation rental",
}
_EXPLICIT_AIR_TRANSPORT_LABELS = {
    "air transport",
    "air transportation",
    "air travel",
    "domestic air transport",
    "domestic air transportation",
    "domestic air travel",
    "international air transport",
    "international air transportation",
    "international air travel",
}
_FLIGHT_ACTIVITY_CATEGORY_LABELS = {
    "air fare",
    "air ticket",
    "air tickets",
    "air transport",
    "air transportation",
    "air travel",
    "airfare",
    "airline ticket",
    "airline tickets",
    "domestic flight",
    "domestic flights",
    "flight",
    "flight ticket",
    "flight tickets",
    "flights",
    "international flight",
    "international flights",
}


def _is_excluded_budget_item(item: object) -> bool:
    if isinstance(item, BudgetItem):
        category = item.category
    elif isinstance(item, dict):
        category = item.get("category")
    else:
        return False
    return isinstance(category, str) and _is_excluded_base_budget_category(category)


def _is_excluded_base_budget_category(category: str) -> bool:
    """Match only controlled airfare and room-cost category labels."""

    normalized = _normalized_cost_label(category)
    if normalized in _EXPLICIT_AIR_TRANSPORT_LABELS:
        return True
    if _AIRFARE_LABEL.fullmatch(normalized):
        return True

    without_prefix = re.sub(r"^(?:estimated|total) ", "", normalized)
    without_nights = re.sub(r" (?:for )?\d+ nights?$", "", without_prefix)
    without_suffix = re.sub(
        r" (?:rate|rates|cost|costs|expense|expenses)$",
        "",
        without_nights,
    )
    return without_suffix in _LODGING_CORE_LABELS


def _is_lodging_room_activity(name: str, category: str) -> bool:
    """Classify explicit room/stay logistics without matching nearby expenses."""

    normalized_category = _normalized_cost_label(category)
    if normalized_category in _LODGING_CORE_LABELS:
        return True

    normalized_name = _normalized_cost_label(name)
    return bool(
        re.fullmatch(
            r"(?:hotel|hostel|resort|airbnb) check in|"
            r"check in (?:at|to) (?:the )?(?:hotel|hostel|resort|airbnb)|"
            r"stay at (?:the )?(?:hotel|hostel|resort|airbnb)|"
            r"overnight (?:accommodation|lodging)|"
            r"(?:hotel|hostel|resort|airbnb) (?:room|stay|lodging|accommodation)",
            normalized_name,
        )
    )


def _is_flight_ticket_activity(name: str, category: str | None) -> bool:
    """Match explicit airfare activities without matching airport ground travel."""

    normalized_category = _normalized_cost_label(category or "")
    if normalized_category in _FLIGHT_ACTIVITY_CATEGORY_LABELS:
        return True

    normalized_name = _normalized_cost_label(name)
    return bool(
        re.fullmatch(
            r"(?:domestic |international )?flight"
            r"(?: (?:to .+|from .+(?: to .+)?))?|"
            r"(?:airfare|air fare|air ticket|air tickets|flight ticket|"
            r"flight tickets|airline ticket|airline tickets)"
            r"(?: (?:to .+|from .+(?: to .+)?))?",
            normalized_name,
        )
    )
