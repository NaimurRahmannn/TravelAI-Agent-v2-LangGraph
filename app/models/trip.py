from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class Trip(BaseModel):

    origin: Optional[str] = Field(
        default=None,
        description="Departure location"
    )

    destination: Optional[str] = Field(
        default=None,
        description="Travel destination"
    )

    start_date: date | None = None

    end_date: date | None = None

    duration: Optional[int] = Field(
        default=None,
        description="Number of travel days"
    )

    budget: Optional[float] = None

    budget_original: Optional[float] = Field(
        default=None,
        description="Budget as originally stated by the traveler, before "
                     "conversion to USD (only set when a conversion happened)",
    )

    currency: Optional[str] = Field(
        default=None,
        description="ISO 4217 currency code (e.g. USD, BDT, EUR, INR) for "
                     "the budget figure, determined ONLY from how the amount "
                     "itself was written in the message (a '$' sign or 'USD' "
                     "-> USD; 'tk', 'taka', 'BDT', '৳' -> BDT; etc). Never "
                     "inferred from the traveler's origin, nationality, or "
                     "destination.",
    )

    travelers: Optional[int] = Field(
        default=None,
        ge=1
    )

    preferences: list[str] = Field(
        default_factory=list
    )


class TripExtraction(BaseModel):
    """Strict LLM output schema; every key is required but may be null."""

    model_config = ConfigDict(extra="forbid")

    origin: str | None = Field(description="Departure location stated by the user")
    destination: str | None = Field(description="Travel destination stated by the user")
    start_date: str | None = Field(description="Start date stated by the user")
    end_date: str | None = Field(description="End date stated by the user")
    duration: int | None = Field(description="Number of travel days stated by the user")
    budget: float | None = Field(description="Numeric travel budget stated by the user")
    currency: str | None = Field(
        description="ISO 4217 code inferred only from the written budget symbol or name"
    )
    travelers: int | None = Field(
        description="Number of travelers explicitly stated by the user",
        ge=1,
    )
    preferences: list[str] = Field(
        description="Travel preferences newly stated by the user"
    )
