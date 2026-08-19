import {
  ArrowRight,
  CalendarRange,
  Clock3,
  MapPinned,
  UsersRound,
} from "lucide-react";
import type { TripPlan } from "@/lib/api";
import { formatActivityCategory } from "./formatters";

type TripOverviewProps = {
  itinerary: TripPlan;
};

export function TripOverview({ itinerary }: TripOverviewProps) {
  const formattedRange = formatTripDateRange(
    itinerary.start_date,
    itinerary.end_date,
  );

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
        {formattedRange ? (
          <span>
            <CalendarRange aria-hidden="true" size={17} />
            {formattedRange}
          </span>
        ) : null}
        <span>
          <Clock3 aria-hidden="true" size={17} />
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

function formatTripDateRange(
  startDate?: string | null,
  endDate?: string | null,
): string | null {
  const start = parseIsoDate(startDate);
  const end = parseIsoDate(endDate);
  if (!start || !end) {
    return null;
  }

  const sameYear = start.getFullYear() === end.getFullYear();
  const sameMonth = sameYear && start.getMonth() === end.getMonth();
  const shortDate = new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
  });
  const fullDate = new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });

  if (start.getTime() === end.getTime()) {
    return fullDate.format(start);
  }
  if (sameMonth) {
    const month = new Intl.DateTimeFormat("en-US", { month: "short" }).format(start);
    return `${month} ${start.getDate()} - ${end.getDate()}, ${end.getFullYear()}`;
  }
  if (sameYear) {
    return `${shortDate.format(start)} - ${fullDate.format(end)}`;
  }
  return `${fullDate.format(start)} - ${fullDate.format(end)}`;
}

function parseIsoDate(value?: string | null): Date | null {
  if (!value) {
    return null;
  }
  const parts = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!parts) {
    return null;
  }
  return new Date(Number(parts[1]), Number(parts[2]) - 1, Number(parts[3]));
}
