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

    currency: Optional[str] = None

    travelers: Optional[int] = Field(
        default=1,
        ge=1
    )

    preferences: list[str] = Field(
        default_factory=list
    )