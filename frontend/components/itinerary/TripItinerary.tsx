import type { TripPlan } from "@/lib/api";
import { BudgetSummary } from "./BudgetSummary";
import { ItineraryDay } from "./ItineraryDay";
import { PracticalNotes } from "./PracticalNotes";
import { TripOverview } from "./TripOverview";

type TripItineraryProps = {
  itinerary: TripPlan;
};

export function TripItinerary({ itinerary }: TripItineraryProps) {
  return (
    <div className="tripItinerary">
      <TripOverview itinerary={itinerary} />
      <div className="itineraryDays">
        {itinerary.days.map((day) => (
          <ItineraryDay day={day} key={day.day_number} />
        ))}
      </div>
      <div className="tripFooterGrid">
        <BudgetSummary budget={itinerary.budget} />
        <PracticalNotes notes={itinerary.practical_notes} />
      </div>
    </div>
  );
}
