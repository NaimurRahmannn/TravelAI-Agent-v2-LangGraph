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

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
RecommendationStatus = Literal[
    "not_searched",
    "available",
    "no_results",
    "no_affordable_results",
    "unavailable",
]
BudgetEvaluationStatus = Literal["within_budget", "over_budget", "unknown"]
BudgetEvaluationReason = Literal[
    "within_total_budget",
    "exceeds_total_budget",
    "missing_user_budget",
    "currency_mismatch",
]


class _ProviderOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: NonEmptyString

    @field_validator("provider", mode="before")
    @classmethod
    def normalize_provider(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().casefold()
        return value


class FlightOption(_ProviderOption):
    """Provider-neutral, provider-authoritative flight offer."""

    provider_offer_id: NonEmptyString
    origin_code: NonEmptyString
    destination_code: NonEmptyString
    departure_at: datetime
    arrival_at: datetime
    total_duration_minutes: int = Field(ge=1)
    stops: int = Field(ge=0)
    total_price: float = Field(ge=0)
    currency: str
    external_url: str | None = None
    fetched_at: datetime

    @field_validator("origin_code", "destination_code", mode="before")
    @classmethod
    def normalize_location_code(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("currency", mode="before")
    @classmethod
    def validate_currency(cls, value: object) -> object:
        return _normalize_currency(value)

    @field_validator("external_url", mode="before")
    @classmethod
    def validate_external_url(cls, value: object) -> object:
        return _validate_optional_http_url(value)

    @model_validator(mode="after")
    def validate_schedule(self) -> "FlightOption":
        if self.arrival_at <= self.departure_at:
            raise ValueError("Flight arrival must be after departure")
        return self


class HotelOption(_ProviderOption):
    """Provider-neutral, provider-authoritative total-stay hotel offer."""

    provider_hotel_id: NonEmptyString
    name: NonEmptyString
    city: str | None = None
    country: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    check_in: CalendarDate
    check_out: CalendarDate
    nights: int = Field(ge=1)
    total_price: float = Field(ge=0)
    currency: str
    price_per_night: float | None = Field(default=None, ge=0)
    rating: float | None = Field(default=None, ge=0)
    review_count: int | None = Field(default=None, ge=0)
    image_url: str | None = None
    external_url: str | None = None
    fetched_at: datetime

    @field_validator("currency", mode="before")
    @classmethod
    def validate_currency(cls, value: object) -> object:
        return _normalize_currency(value)

    @field_validator("image_url", "external_url", mode="before")
    @classmethod
    def validate_external_url(cls, value: object) -> object:
        return _validate_optional_http_url(value)

    @model_validator(mode="after")
    def validate_stay(self) -> "HotelOption":
        expected_nights = (self.check_out - self.check_in).days
        if expected_nights < 1:
            raise ValueError("Hotel check-out must be after check-in")
        if self.nights != expected_nights:
            raise ValueError("Hotel nights must match check-in and check-out")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Hotel latitude and longitude must be supplied together")
        return self


class RestaurantRecommendation(_ProviderOption):
    """Provider-backed restaurant place facts without invented meal prices."""

    provider_place_id: NonEmptyString
    name: NonEmptyString
    formatted_address: str | None = None
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    categories: list[str] = Field(default_factory=list)
    cuisine: list[str] = Field(default_factory=list)
    distance_meters: float | None = Field(default=None, ge=0)
    price_level: str | None = None
    external_url: str | None = None

    @field_validator("external_url", mode="before")
    @classmethod
    def validate_external_url(cls, value: object) -> object:
        return _validate_optional_http_url(value)


class RecommendationDomainState(BaseModel):
    """Search outcome metadata without exposing rejected provider payloads."""

    model_config = ConfigDict(extra="forbid")

    status: RecommendationStatus = "not_searched"
    provider_result_count: int = Field(default=0, ge=0)
    affordable_result_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> "RecommendationDomainState":
        if self.affordable_result_count > self.provider_result_count:
            raise ValueError("Affordable count cannot exceed provider result count")
        if self.status in {"not_searched", "no_results", "unavailable"} and (
            self.provider_result_count != 0 or self.affordable_result_count != 0
        ):
            raise ValueError(f"{self.status} status cannot include result counts")
        if self.status == "no_affordable_results" and (
            self.provider_result_count == 0 or self.affordable_result_count != 0
        ):
            raise ValueError("No-affordable-results status requires rejected results")
        if self.status == "available" and self.affordable_result_count == 0:
            raise ValueError("Available status requires affordable results")
        return self


class TravelRecommendations(BaseModel):
    """Traveler-facing recommendations and non-sensitive search summaries."""

    model_config = ConfigDict(extra="forbid")

    flights: list[FlightOption] = Field(default_factory=list)
    hotels: list[HotelOption] = Field(default_factory=list)
    restaurants: list[RestaurantRecommendation] = Field(default_factory=list)
    flight_status: RecommendationDomainState = Field(
        default_factory=RecommendationDomainState
    )
    hotel_status: RecommendationDomainState = Field(
        default_factory=RecommendationDomainState
    )
    restaurant_status: RecommendationDomainState = Field(
        default_factory=RecommendationDomainState
    )


class FlightSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin: NonEmptyString
    destination: NonEmptyString
    departure_date: CalendarDate
    return_date: CalendarDate | None = None
    adults: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_dates(self) -> "FlightSearchRequest":
        if self.return_date is not None and self.return_date < self.departure_date:
            raise ValueError("Flight return date cannot be before departure date")
        return self


class HotelSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination: NonEmptyString
    city: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    check_in: CalendarDate
    check_out: CalendarDate
    travelers: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_stay(self) -> "HotelSearchRequest":
        if self.check_out <= self.check_in:
            raise ValueError("Hotel search check-out must be after check-in")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Hotel search coordinates must be supplied together")
        return self


class RestaurantSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day_number: int = Field(ge=1)
    date: CalendarDate | None = None
    city: NonEmptyString
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    preferences: list[str] = Field(default_factory=list)


class RecommendationBudgetContext(BaseModel):
    """USD itinerary allocations used when projecting real provider prices."""

    model_config = ConfigDict(extra="forbid")

    user_budget_usd: float | None = Field(default=None, ge=0)
    estimated_flight_usd: float = Field(ge=0)
    estimated_hotel_usd: float = Field(ge=0)
    estimated_other_trip_cost_usd: float = Field(ge=0)


class BudgetEvaluation(BaseModel):
    """Deterministic projected-total comparison result."""

    model_config = ConfigDict(extra="forbid")

    status: BudgetEvaluationStatus
    reason: BudgetEvaluationReason
    projected_trip_total_usd: float | None = Field(default=None, ge=0)
    remaining_budget_usd: float | None = None


def _normalize_currency(value: object) -> object:
    if not isinstance(value, str):
        return value
    normalized = value.strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise ValueError("Currency must be a three-letter code")
    return normalized


def _validate_optional_http_url(value: object) -> object:
    if value is None:
        return value
    if not isinstance(value, str):
        raise ValueError("External URLs must be strings")
    normalized = value.strip()
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("External URLs must use HTTP(S)")
    return normalized
