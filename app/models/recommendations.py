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

from app.models.hotel_stays import build_hotel_stay_key

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
RecommendationStatus = Literal[
    "not_searched",
    "available",
    "no_results",
    "unavailable",
]
FlightPriceType = Literal["shopping_total"]


class _ProviderOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: NonEmptyString

    @field_validator("provider", mode="before")
    @classmethod
    def normalize_provider(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().casefold()
        return value


class FlightSegment(BaseModel):
    """One provider-reported flight segment within a requested journey leg."""

    model_config = ConfigDict(extra="forbid")

    origin_code: NonEmptyString
    destination_code: NonEmptyString
    departure_at: datetime
    arrival_at: datetime
    duration_minutes: int = Field(ge=1)
    airline_code: str | None = None
    airline_name: str | None = None
    operator_name: str | None = None
    flight_number: str | None = None
    aircraft: str | None = None

    @field_validator(
        "origin_code",
        "destination_code",
        "airline_code",
        mode="before",
    )
    @classmethod
    def normalize_codes(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_schedule(self) -> "FlightSegment":
        if self.arrival_at <= self.departure_at:
            raise ValueError("Flight segment arrival must be after departure")
        return self


class FlightLayover(BaseModel):
    """One provider-reported connection between flight segments."""

    model_config = ConfigDict(extra="forbid")

    airport_code: str | None = None
    airport_name: str | None = None
    city: str | None = None
    duration_minutes: int = Field(ge=0)
    is_overnight: bool = False

    @field_validator("airport_code", mode="before")
    @classmethod
    def normalize_airport_code(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class FlightSlice(BaseModel):
    """One outbound, return, or multi-city journey leg from the provider."""

    model_config = ConfigDict(extra="forbid")

    origin_code: NonEmptyString
    destination_code: NonEmptyString
    departure_at: datetime
    arrival_at: datetime
    duration_minutes: int = Field(ge=1)
    stops: int = Field(ge=0)
    segments: list[FlightSegment] = Field(min_length=1)
    layovers: list[FlightLayover] = Field(default_factory=list)

    @field_validator("origin_code", "destination_code", mode="before")
    @classmethod
    def normalize_codes(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_journey(self) -> "FlightSlice":
        if self.arrival_at <= self.departure_at:
            raise ValueError("Flight slice arrival must be after departure")
        if self.segments[0].origin_code != self.origin_code:
            raise ValueError("Flight slice origin must match its first segment")
        if self.segments[-1].destination_code != self.destination_code:
            raise ValueError("Flight slice destination must match its last segment")
        for previous, current in zip(self.segments, self.segments[1:]):
            if previous.destination_code != current.origin_code:
                raise ValueError("Flight slice segments must be contiguous")
        return self


class FlightOption(_ProviderOption):
    """A provider-neutral flight shopping result for the complete query."""

    provider: Literal["swoop"]
    provider_offer_id: NonEmptyString
    origin_code: NonEmptyString
    destination_code: NonEmptyString
    adults: int = Field(ge=1)
    total_duration_minutes: int = Field(ge=1)
    stops: int = Field(ge=0)
    total_price: float = Field(ge=0)
    currency: str
    price_type: FlightPriceType
    airline_names: list[str] = Field(default_factory=list)
    slices: list[FlightSlice] = Field(min_length=1)
    fetched_at: datetime

    @field_validator("origin_code", "destination_code", mode="before")
    @classmethod
    def normalize_location_code(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("currency", mode="before")
    @classmethod
    def validate_currency(cls, value: object) -> object:
        return _normalize_currency(value)

    @field_validator("airline_names")
    @classmethod
    def deduplicate_airlines(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(name.strip() for name in value if name.strip()))

    @model_validator(mode="after")
    def validate_summary(self) -> "FlightOption":
        if self.origin_code != self.slices[0].origin_code:
            raise ValueError("Flight origin must match the first slice")
        if self.destination_code != self.slices[0].destination_code:
            raise ValueError("Flight destination must match the first slice")
        if self.total_duration_minutes != sum(
            item.duration_minutes for item in self.slices
        ):
            raise ValueError("Flight duration must equal its slice durations")
        if self.stops != sum(item.stops for item in self.slices):
            raise ValueError("Flight stops must equal its slice stops")
        return self


class HotelOption(_ProviderOption):
    """Provider-neutral, provider-authoritative total-stay hotel offer."""

    provider_hotel_id: NonEmptyString
    provider_offer_id: NonEmptyString
    stay_key: NonEmptyString
    name: NonEmptyString
    city: str | None = None
    country: str | None = None
    formatted_address: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    check_in: CalendarDate
    check_out: CalendarDate
    nights: int = Field(ge=1)
    total_price: float = Field(ge=0)
    currency: str
    price_per_night: float | None = Field(default=None, ge=0)
    room_name: str | None = None
    board_name: str | None = None
    rating: float | None = Field(default=None, ge=0)
    review_count: int | None = Field(default=None, ge=0)
    refundable: bool | None = None
    taxes_included: bool | None = None
    image_url: str | None = None
    external_url: str | None = None
    is_sandbox: bool = False
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
        if self.stay_key != build_hotel_stay_key(
            self.city,
            self.check_in,
            self.check_out,
        ):
            raise ValueError("Hotel stay key must match city and stay dates")
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

    @model_validator(mode="after")
    def validate_counts(self) -> "RecommendationDomainState":
        if (
            self.status in {"not_searched", "no_results", "unavailable"}
            and self.provider_result_count != 0
        ):
            raise ValueError(f"{self.status} status cannot include result counts")
        if self.status == "available" and self.provider_result_count == 0:
            raise ValueError("Available status requires provider results")
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
    return_origin: str | None = None
    return_destination: str | None = None
    origin_country_hint: str | None = None
    destination_country_hint: str | None = None
    return_origin_country_hint: str | None = None
    return_destination_country_hint: str | None = None
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

    city: NonEmptyString
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    check_in: CalendarDate
    check_out: CalendarDate
    adults: int = Field(ge=1)
    guest_nationality_country_code: str
    radius_meters: int = Field(ge=1, le=50_000)

    @field_validator("guest_nationality_country_code", mode="before")
    @classmethod
    def normalize_guest_nationality(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("Guest nationality must be an ISO-2 country code")
        normalized = value.strip().upper()
        if len(normalized) != 2 or not normalized.isalpha():
            raise ValueError("Guest nationality must be an ISO-2 country code")
        return normalized

    @model_validator(mode="after")
    def validate_stay(self) -> "HotelSearchRequest":
        if self.check_out <= self.check_in:
            raise ValueError("Hotel search check-out must be after check-in")
        return self


class RestaurantSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day_number: int = Field(ge=1)
    date: CalendarDate | None = None
    city: NonEmptyString
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    preferences: list[str] = Field(default_factory=list)


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
