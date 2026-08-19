import { CalendarDays, Coins } from "lucide-react";
import type { ItineraryDay as ItineraryDayData } from "@/lib/api";
import {
  buildActivityDomId,
  type ItineraryMapPoint,
} from "@/lib/itineraryMap";
import { ActivityCard } from "./ActivityCard";
import { formatItineraryDate, formatUsd } from "./formatters";

type ItineraryDayProps = {
  day: ItineraryDayData;
  idPrefix: string;
  mapPoints: readonly ItineraryMapPoint[];
  mapReady: boolean;
  onShowOnMap: (pointId: string) => void;
  selectedMapPointId: string | null;
};

export function ItineraryDay({
  day,
  idPrefix,
  mapPoints,
  mapReady,
  onShowOnMap,
  selectedMapPointId,
}: ItineraryDayProps) {
  const formattedDate = formatItineraryDate(day.date);
  const headingId = `${idPrefix}-day-${day.day_number}-heading`;

  return (
    <section aria-labelledby={headingId} className="itineraryDay">
      <header className="dayHeader">
        <div className="dayIdentity">
          <span>Day {day.day_number}</span>
          <h3 id={headingId}>{day.city}</h3>
        </div>
        <div className="dayFacts">
          {formattedDate ? (
            <div>
              <CalendarDays aria-hidden="true" size={15} />
              <time dateTime={day.date ?? undefined}>{formattedDate}</time>
            </div>
          ) : null}
          {day.estimated_daily_cost_usd != null ? (
            <div>
              <Coins aria-hidden="true" size={15} />
              <span>Daily estimate {formatUsd(day.estimated_daily_cost_usd)}</span>
            </div>
          ) : null}
        </div>
      </header>

      <div className="activityList">
        {day.activities.map((activity, index) => {
          const mapPoint = mapPoints.find(
            (point) => point.activityIndex === index,
          );
          const identity =
            activity.place?.provider_place_id ??
            `${activity.name.toLocaleLowerCase()}-${index}`;
          return (
            <ActivityCard
              activity={activity}
              activityDomId={buildActivityDomId(
                idPrefix,
                day.day_number,
                index,
              )}
              isMapSelected={mapPoint?.id === selectedMapPointId}
              key={`${day.day_number}-${index}-${identity}`}
              mapPointId={mapPoint?.id}
              mapReady={mapReady}
              onShowOnMap={onShowOnMap}
            />
          );
        })}
      </div>
    </section>
  );
}
