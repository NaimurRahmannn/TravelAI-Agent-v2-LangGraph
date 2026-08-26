from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.recommendations import NonEmptyString

SelectionStatus = Literal["not_required", "required", "selected", "unavailable"]


class TravelSelectionStatus(BaseModel):
    """Deterministic frontend state for the current recommendation snapshot."""

    model_config = ConfigDict(extra="forbid")

    flight: SelectionStatus = "not_required"
    hotel: SelectionStatus = "not_required"


class SelectedHotelStay(BaseModel):
    """An IDs-only traveler choice for one required hotel stay."""

    model_config = ConfigDict(extra="forbid")

    stay_key: str = Field(pattern=r"^stay_[0-9a-f]{16}$")
    hotel_option_id: NonEmptyString


class TravelSelections(BaseModel):
    """Thread-scoped user choices referencing one recommendation snapshot."""

    model_config = ConfigDict(extra="forbid")

    selected_flight_id: NonEmptyString
    selected_hotels: list[SelectedHotelStay] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_stays(self) -> "TravelSelections":
        stay_keys = [selection.stay_key for selection in self.selected_hotels]
        if len(stay_keys) != len(set(stay_keys)):
            raise ValueError("Only one hotel may be selected per stay")
        return self


class TripCostSummary(BaseModel):
    """Python-calculated combined estimate without mutating the base budget."""

    model_config = ConfigDict(extra="forbid")

    base_trip_total_usd: float = Field(ge=0)
    selected_flight_usd: float = Field(ge=0)
    selected_hotels_usd: float = Field(ge=0)
    additions_total_usd: float = Field(ge=0)
    updated_trip_total_usd: float = Field(ge=0)
    user_budget_usd: float | None = Field(default=None, ge=0)
    difference_from_budget_usd: float | None = None

    @model_validator(mode="after")
    def validate_totals(self) -> "TripCostSummary":
        additions = round(self.selected_flight_usd + self.selected_hotels_usd, 2)
        updated = round(self.base_trip_total_usd + additions, 2)
        if self.additions_total_usd != additions:
            raise ValueError("Travel additions must equal flight plus hotel totals")
        if self.updated_trip_total_usd != updated:
            raise ValueError("Updated trip total must include base and additions")
        if self.user_budget_usd is None:
            if self.difference_from_budget_usd is not None:
                raise ValueError("A budget difference requires a user budget")
        else:
            difference = round(updated - self.user_budget_usd, 2)
            if self.difference_from_budget_usd != difference:
                raise ValueError("Budget difference does not match the updated total")
        return self
