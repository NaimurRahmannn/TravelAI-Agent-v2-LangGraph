import { Bike, BusFront, Car, Footprints } from "lucide-react";
import type { TravelLeg, TravelMode } from "@/lib/api";
import {
  formatTravelDistance,
  formatTravelDuration,
  formatTravelMode,
} from "./formatters";

export function TravelLegConnector({ leg }: { leg: TravelLeg }) {
  const ModeIcon = modeIcons[leg.mode];
  const isResolved =
    leg.status === "resolved" &&
    leg.distance_meters != null &&
    leg.duration_seconds != null;

  return (
    <div
      aria-label={`Travel from ${leg.from_name} to ${leg.to_name}`}
      className={`travelLegConnector${isResolved ? "" : " travelLegUnavailable"}`}
    >
      <span className="travelLegLine" aria-hidden="true" />
      <span className="travelLegSummary">
        <ModeIcon aria-hidden="true" size={15} />
        {isResolved ? (
          <>
            <strong>Estimated {formatTravelMode(leg.mode).toLowerCase()}</strong>
            <span>{formatTravelDuration(leg.duration_seconds!)}</span>
            <span>{formatTravelDistance(leg.distance_meters!)}</span>
            <small>No live traffic</small>
          </>
        ) : (
          <span>{formatTravelMode(leg.mode)} estimate unavailable</span>
        )}
      </span>
    </div>
  );
}

const modeIcons: Record<TravelMode, typeof Footprints> = {
  walk: Footprints,
  drive: Car,
  transit: BusFront,
  bicycle: Bike,
};
