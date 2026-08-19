"use client";

import {
  ArrowRight,
  CalendarClock,
  CalendarRange,
  Clock3,
  MapPinned,
  UsersRound,
} from "lucide-react";
import { useState } from "react";
import type { TripPlan } from "@/lib/api";
import { parseIsoDate, TravelDatePicker } from "../TravelDatePicker";
import { formatActivityCategory } from "./formatters";

type TripOverviewProps = {
  isUpdatingDates?: boolean;
  itinerary: TripPlan;
  onDateUpdate?: (startDate: string, endDate: string) => Promise<void> | void;
};

export function TripOverview({
  isUpdatingDates = false,
  itinerary,
  onDateUpdate,
}: TripOverviewProps) {
  const [isEditingDates, setIsEditingDates] = useState(false);
  const formattedRange = formatTripDateRange(
    itinerary.start_date,
    itinerary.end_date,
  );
  const canEditDates =
    formattedRange !== null &&
    itinerary.start_date !== undefined &&
    itinerary.start_date !== null &&
    itinerary.end_date !== undefined &&
    itinerary.end_date !== null &&
    onDateUpdate !== undefined;

  async function handleDateUpdate(startDate: string, endDate: string) {
    if (!onDateUpdate) {
      return;
    }
    await onDateUpdate(startDate, endDate);
    setIsEditingDates(false);
  }

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
        {canEditDates && !isEditingDates ? (
          <button
            className="changeDatesButton"
            disabled={isUpdatingDates}
            onClick={() => setIsEditingDates(true)}
            type="button"
          >
            <CalendarClock aria-hidden="true" size={16} />
            Change dates
          </button>
        ) : null}
      </div>

      {canEditDates && isEditingDates ? (
        <div className="tripDateEditor">
          <TravelDatePicker
            disabled={isUpdatingDates}
            initialEndDate={itinerary.end_date}
            initialStartDate={itinerary.start_date}
            onCancel={() => setIsEditingDates(false)}
            onContinue={handleDateUpdate}
            submitLabel="Update dates"
            title="Change your travel dates"
          />
        </div>
      ) : null}

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
  if (!start || !end || end < start) {
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
