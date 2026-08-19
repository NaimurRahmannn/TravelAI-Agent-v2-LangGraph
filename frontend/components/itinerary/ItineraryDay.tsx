import { CalendarDays, CloudSun, Coins, Droplets, Wind } from "lucide-react";
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

      <DayWeather day={day} />

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

function DayWeather({ day }: { day: ItineraryDayData }) {
  if (day.weather_status === "skipped") {
    return null;
  }

  if (day.weather_status === "outside_forecast_horizon") {
    return (
      <p className="dayWeatherFallback">
        Forecast not available yet.
      </p>
    );
  }

  if (day.weather_status === "unavailable" || !day.weather) {
    return <p className="dayWeatherFallback">Weather unavailable.</p>;
  }

  const weather = day.weather;
  const condition = weather.description?.trim() || weather.condition;

  return (
    <aside aria-label={`Weather forecast for day ${day.day_number}`} className="dayWeather">
      <div className="dayWeatherCondition">
        <CloudSun aria-hidden="true" size={18} />
        <span>{condition}</span>
      </div>
      <span className="dayWeatherTemperature">
        {Math.round(weather.min_temperature_c)}-{Math.round(weather.max_temperature_c)}°C
      </span>
      {weather.precipitation_probability_pct != null ? (
        <span className="dayWeatherMetric">
          <Droplets aria-hidden="true" size={14} />
          {Math.round(weather.precipitation_probability_pct)}%
        </span>
      ) : null}
      {weather.wind_speed_mps != null ? (
        <span className="dayWeatherMetric">
          <Wind aria-hidden="true" size={14} />
          {weather.wind_speed_mps.toFixed(1)} m/s
        </span>
      ) : null}
      <a
        className="dayWeatherAttribution"
        href="https://openweathermap.org/"
        rel="noopener noreferrer"
        target="_blank"
      >
        Weather data by OpenWeather
      </a>
    </aside>
  );
}
