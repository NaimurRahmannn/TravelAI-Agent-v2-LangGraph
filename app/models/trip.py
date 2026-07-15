from pydantic import BaseModel, Field
from typing import Optional


class Trip(BaseModel):

    origin: Optional[str] = Field(
        default=None,
        description="Departure location"
    )

    destination: Optional[str] = Field(
        default=None,
        description="Travel destination"
    )

    start_date: Optional[str] = None

    end_date: Optional[str] = None

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
        default=1,
        ge=1
    )

    preferences: list[str] = Field(
        default_factory=list
    )