import re
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models import TripPlan
from app.services.trip_dates import validate_and_derive_duration

StreamMode = Literal["updates", "messages", "debug"]


class ChatRequest(BaseModel):
    """Request body for a chat invocation."""

    message: str
    thread_id: Optional[str] = None
    user_id: Optional[str] = None
    stream_mode: StreamMode = "messages"
    start_date: date | None = None
    end_date: date | None = None

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def validate_iso_date(cls, value: object) -> object:
        """Require API date strings to use the unambiguous ISO date format."""

        if isinstance(value, str) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Dates must use YYYY-MM-DD format")
        return value

    @model_validator(mode="after")
    def validate_date_selection(self) -> "ChatRequest":
        """Accept either no picker selection or one complete, valid range."""

        if (self.start_date is None) != (self.end_date is None):
            raise ValueError("Both start_date and end_date are required")
        if self.start_date is not None and self.end_date is not None:
            validate_and_derive_duration(self.start_date, self.end_date)
        return self


class ChatResponse(BaseModel):
    """Response body returned by the travel graph."""

    response: str
    thread_id: str
    itinerary: TripPlan | None = None
    missing_fields: list[str] = Field(default_factory=list)


class MapsConfigResponse(BaseModel):
    """Public browser configuration for map visualization."""

    enabled: bool
    api_key: str | None = None
