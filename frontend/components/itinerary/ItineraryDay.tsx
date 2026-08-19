import { CalendarDays, Coins } from "lucide-react";
import type { ItineraryDay as ItineraryDayData } from "@/lib/api";
import { ActivityCard } from "./ActivityCard";
import { formatItineraryDate, formatUsd } from "./formatters";

type ItineraryDayProps = {
  day: ItineraryDayData;
};

export function ItineraryDay({ day }: ItineraryDayProps) {
  const formattedDate = formatItineraryDate(day.date);

  return (
    <section aria-labelledby={`day-${day.day_number}`} className="itineraryDay">
      <header className="dayHeader">
        <div className="dayIdentity">
          <span>Day {day.day_number}</span>
          <h3 id={`day-${day.day_number}`}>{day.city}</h3>
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
          const identity =
            activity.place?.provider_place_id ??
            `${activity.name.toLocaleLowerCase()}-${index}`;
          return (
            <ActivityCard
              activity={activity}
              key={`${day.day_number}-${identity}`}
            />
          );
        })}
      </div>
    </section>
  );
}
