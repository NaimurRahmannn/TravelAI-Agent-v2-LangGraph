from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.recommendations import FlightSearchScope


TurnIntent = Literal[
    "create_trip",
    "modify_trip",
    "extend_trip",
    "suggest_outbound_flights",
    "suggest_return_flights",
    "suggest_round_trip_flights",
    "suggest_hotels",
    "answer_question",
    "unsupported",
]
ChangedTripField = Literal[
    "origin",
    "destination",
    "dates",
    "duration",
    "budget",
    "travelers",
    "preferences",
    "activities",
]


class TurnDecision(BaseModel):
    """One safe, structured decision for the current conversational turn."""

    model_config = ConfigDict(extra="forbid")

    intent: TurnIntent
    flight_scope: FlightSearchScope | None
    extension_days: int | None = Field(ge=1, le=30)
    changed_fields: list[ChangedTripField]
    refresh_hotels: bool

    @model_validator(mode="after")
    def validate_intent_details(self) -> "TurnDecision":
        flight_intents = {
            "suggest_outbound_flights": "outbound",
            "suggest_return_flights": "return",
            "suggest_round_trip_flights": "round_trip",
        }
        expected_scope = flight_intents.get(self.intent)
        if expected_scope is not None and self.flight_scope != expected_scope:
            raise ValueError("Flight intent and scope must agree")
        if expected_scope is None and self.flight_scope is not None:
            raise ValueError("Only flight intents may include a flight scope")
        if self.intent == "extend_trip" and self.extension_days is None:
            raise ValueError("Trip extension intent requires extension_days")
        if self.intent != "extend_trip" and self.extension_days is not None:
            raise ValueError("Only trip extensions may include extension_days")
        return self
