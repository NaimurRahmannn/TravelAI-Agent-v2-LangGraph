import { ArrowRight, CalendarRange, MapPinned, UsersRound } from "lucide-react";
import type { TripPlan } from "@/lib/api";
import { formatActivityCategory } from "./formatters";

type TripOverviewProps = {
  itinerary: TripPlan;
};

export function TripOverview({ itinerary }: TripOverviewProps) {
  return (
    <header className="tripOverview">
      <div className="overviewGlow" aria-hidden="true" />
      <span className="tripEyebrow">Your itinerary</span>
      <h2>{itinerary.title}</h2>

      <div className="tripRoute" aria-label="Trip route">
        <MapPinned aria-hidden="true" size={18} />
        {itinerary.origin ? (
          <>
            <span>{itinerary.origin}</span>
            <ArrowRight aria-hidden="true" size={16} />
          </>
        ) : null}
        <strong>{itinerary.destination}</strong>
      </div>

      <div className="tripStats">
        <span>
          <CalendarRange aria-hidden="true" size={17} />
          {itinerary.duration_days} {itinerary.duration_days === 1 ? "day" : "days"}
        </span>
        <span>
          <UsersRound aria-hidden="true" size={17} />
          {itinerary.travelers} {itinerary.travelers === 1 ? "traveler" : "travelers"}
        </span>
      </div>

      {itinerary.preferences.length > 0 ? (
        <ul aria-label="Trip preferences" className="preferenceList">
          {itinerary.preferences.map((preference, index) => (
            <li key={`${preference}-${index}`}>
              {formatActivityCategory(preference)}
            </li>
          ))}
        </ul>
      ) : null}

      {itinerary.summary ? <p className="tripSummary">{itinerary.summary}</p> : null}
    </header>
  );
}
