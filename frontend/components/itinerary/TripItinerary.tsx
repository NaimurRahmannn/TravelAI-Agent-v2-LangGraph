import { useId } from "react";
import type { TripPlan } from "@/lib/api";
import { BudgetSummary } from "./BudgetSummary";
import { ItineraryDay } from "./ItineraryDay";
import { PracticalNotes } from "./PracticalNotes";
import { TripOverview } from "./TripOverview";

type TripItineraryProps = {
  itinerary: TripPlan;
};

export function TripItinerary({ itinerary }: TripItineraryProps) {
  const idPrefix = useId();

  return (
    <div className="tripItinerary">
      <TripOverview itinerary={itinerary} />
      <div className="itineraryDays">
        {itinerary.days.map((day) => (
          <ItineraryDay day={day} idPrefix={idPrefix} key={day.day_number} />
        ))}
      </div>
      <div className="tripFooterGrid">
        <BudgetSummary budget={itinerary.budget} idPrefix={idPrefix} />
        <PracticalNotes idPrefix={idPrefix} notes={itinerary.practical_notes} />
      </div>
    </div>
  );
}
