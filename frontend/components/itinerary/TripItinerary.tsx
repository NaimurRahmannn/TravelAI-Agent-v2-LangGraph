"use client";

import { useId, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import type { TripPlan } from "@/lib/api";
import { buildItineraryMapPoints } from "@/lib/itineraryMap";
import { BudgetSummary } from "./BudgetSummary";
import { ItineraryDay } from "./ItineraryDay";
import { PracticalNotes } from "./PracticalNotes";
import { TripMap, type TripMapStatus } from "./TripMap";
import { TripOverview } from "./TripOverview";

type TripItineraryProps = {
  isUpdatingDates?: boolean;
  itinerary: TripPlan;
  mapPortalTarget?: HTMLElement | null;
  onDateUpdate?: (startDate: string, endDate: string) => Promise<void> | void;
  showMap?: boolean;
};

export function TripItinerary({
  isUpdatingDates = false,
  itinerary,
  mapPortalTarget,
  onDateUpdate,
  showMap = true,
}: TripItineraryProps) {
  const idPrefix = useId();
  const [mapStatus, setMapStatus] = useState<TripMapStatus>("loading");
  const [selectedMapPointId, setSelectedMapPointId] = useState<string | null>(
    null,
  );
  const mapPoints = useMemo(
    () => buildItineraryMapPoints(itinerary, idPrefix),
    [idPrefix, itinerary],
  );
  const mapSectionId = `${idPrefix}-trip-map`;

  function handleMarkerSelect(pointId: string) {
    setSelectedMapPointId(pointId);
    const point = mapPoints.find((item) => item.id === pointId);
    if (point) {
      document.getElementById(point.activityDomId)?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    }
  }

  function handleShowOnMap(pointId: string) {
    setSelectedMapPointId(pointId);
    document.getElementById(mapSectionId)?.scrollIntoView({
      behavior: "smooth",
      block: "center",
    });
  }

  return (
    <div className="tripItinerary">
      <TripOverview
        isUpdatingDates={isUpdatingDates}
        itinerary={itinerary}
        onDateUpdate={onDateUpdate}
      />
      {showMap && mapPoints.length > 0 && mapPortalTarget
        ? createPortal(
            <TripMap
              mapSectionId={mapSectionId}
              onMarkerSelect={handleMarkerSelect}
              onStatusChange={setMapStatus}
              points={mapPoints}
              selectedMapPointId={selectedMapPointId}
            />,
            mapPortalTarget,
          )
        : null}
      <div className="itineraryDays">
        {itinerary.days.map((day) => {
          const dayMapPoints = mapPoints.filter(
            (point) => point.dayNumber === day.day_number,
          );
          return (
            <ItineraryDay
              day={day}
              idPrefix={idPrefix}
              key={day.day_number}
              mapPoints={dayMapPoints}
              mapReady={showMap && mapStatus === "ready"}
              onShowOnMap={handleShowOnMap}
              selectedMapPointId={selectedMapPointId}
            />
          );
        })}
      </div>
      <div className="tripFooterGrid">
        <BudgetSummary budget={itinerary.budget} idPrefix={idPrefix} />
        <PracticalNotes idPrefix={idPrefix} notes={itinerary.practical_notes} />
      </div>
    </div>
  );
}
