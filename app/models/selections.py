from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.recommendations import NonEmptyString
from app.models.itinerary import TripPlan
from app.models.detailed_routing import DetailedRoutingPlan

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

    selected_flight_id: NonEmptyString | None = None
    selected_outbound_flight_id: NonEmptyString | None = None
    selected_return_flight_id: NonEmptyString | None = None
    selected_hotels: list[SelectedHotelStay] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_stays(self) -> "TravelSelections":
        has_legacy_flight = self.selected_flight_id is not None
        has_leg_flight = (
            self.selected_outbound_flight_id is not None
            or self.selected_return_flight_id is not None
        )
        if not has_legacy_flight and not has_leg_flight and not self.selected_hotels:
            raise ValueError("At least one travel selection is required")
        if has_legacy_flight and has_leg_flight:
            raise ValueError("Use either a bundled flight or separate flight legs")
        if (
            self.selected_outbound_flight_id is None
        ) != (self.selected_return_flight_id is None):
            raise ValueError("Select both outbound and return flight legs")
        stay_keys = [selection.stay_key for selection in self.selected_hotels]
        if len(stay_keys) != len(set(stay_keys)):
            raise ValueError("Only one hotel may be selected per stay")
        return self


class ConfirmedTripSnapshot(BaseModel):
    """Immutable traveler-confirmed pricing and routing for one trip revision."""

    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    itinerary: TripPlan
    selections: TravelSelections
    cost_summary: "TripCostSummary"
    routing_plan: DetailedRoutingPlan | None = None
    status: Literal["current", "stale"] = "current"
    stale_reasons: list[str] = Field(default_factory=list)


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
