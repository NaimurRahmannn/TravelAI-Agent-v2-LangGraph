"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  confirmTravelSelection,
  type TravelSelections,
  type TripCostSummary,
  type TripPlan,
} from "@/lib/api";
import { buildItineraryMapPoints } from "@/lib/itineraryMap";
import { BudgetSummary } from "./BudgetSummary";
import { FlightRecommendations } from "./FlightRecommendations";
import { HotelRecommendations } from "./HotelRecommendations";
import { ItineraryDay } from "./ItineraryDay";
import { PracticalNotes } from "./PracticalNotes";
import { TripMap, type TripMapStatus } from "./TripMap";
import { TripOverview } from "./TripOverview";
import {
  getSelectableHotelStayKeys,
  TravelSelectionWorkflow,
} from "./TravelSelectionWorkflow";

type TripItineraryProps = {
  isUpdatingDates?: boolean;
  itinerary: TripPlan;
  mapPortalTarget?: HTMLElement | null;
  onDateUpdate?: (startDate: string, endDate: string) => Promise<void> | void;
  onTravelSelectionConfirmed?: (
    selections: TravelSelections,
    costSummary: TripCostSummary,
  ) => void;
  showMap?: boolean;
  threadId?: string | null;
  travelSelections?: TravelSelections | null;
  tripCostSummary?: TripCostSummary | null;
};

export function TripItinerary({
  isUpdatingDates = false,
  itinerary,
  mapPortalTarget,
  onDateUpdate,
  onTravelSelectionConfirmed,
  showMap = true,
  threadId,
  travelSelections,
  tripCostSummary,
}: TripItineraryProps) {
  const idPrefix = useId();
  const [mapStatus, setMapStatus] = useState<TripMapStatus>("loading");
  const [selectedMapPointId, setSelectedMapPointId] = useState<string | null>(
    null,
  );
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectionDismissed, setSelectionDismissed] = useState(false);
  const [selectedFlightId, setSelectedFlightId] = useState<string | null>(null);
  const [selectedHotelIds, setSelectedHotelIds] = useState<Record<string, string>>(
    {},
  );
  const [selectionUpdating, setSelectionUpdating] = useState(false);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const shouldScrollToUpdatedCost = useRef(false);
  const mapPoints = useMemo(
    () => buildItineraryMapPoints(itinerary, idPrefix),
    [idPrefix, itinerary],
  );
  const mapSectionId = `${idPrefix}-trip-map`;
  const updatedTripCostSectionId = `${idPrefix}-updated-trip-cost`;
  const recommendationKey = `${itinerary.destination}|${itinerary.start_date}|${itinerary.end_date}|${
    itinerary.recommendations?.flights.map((flight) => flight.provider_offer_id).join(",")
  }|${itinerary.recommendations?.hotels.map((hotel) => hotel.provider_offer_id).join(",")}`;
  const requiredHotelStayKeys = getSelectableHotelStayKeys(itinerary);
  const selectionComplete = Boolean(
    selectedFlightId &&
      requiredHotelStayKeys.length > 0 &&
      requiredHotelStayKeys.every((stayKey) => selectedHotelIds[stayKey]),
  );

  useEffect(() => {
    setSelectionMode(false);
    setSelectionDismissed(false);
    setSelectionError(null);
  }, [recommendationKey]);

  useEffect(() => {
    if (
      !shouldScrollToUpdatedCost.current ||
      selectionMode ||
      !travelSelections ||
      !tripCostSummary
    ) {
      return;
    }

    shouldScrollToUpdatedCost.current = false;
    const frame = requestAnimationFrame(() => {
      const section = document.getElementById(updatedTripCostSectionId);
      section?.scrollIntoView({ behavior: "smooth", block: "start" });
      document
        .getElementById(`${updatedTripCostSectionId}-heading`)
        ?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [
    selectionMode,
    travelSelections,
    tripCostSummary,
    updatedTripCostSectionId,
  ]);

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

  function beginSelection() {
    setSelectedFlightId(travelSelections?.selected_flight_id ?? null);
    setSelectedHotelIds(
      Object.fromEntries(
        (travelSelections?.selected_hotels ?? []).map((selection) => [
          selection.stay_key,
          selection.hotel_option_id,
        ]),
      ),
    );
    setSelectionError(null);
    setSelectionMode(true);
    requestAnimationFrame(() => {
      document.getElementById(`${idPrefix}-flights-heading`)?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    });
  }

  async function confirmSelections() {
    if (!threadId || !selectedFlightId || !selectionComplete || selectionUpdating) {
      return;
    }
    setSelectionUpdating(true);
    setSelectionError(null);
    try {
      const response = await confirmTravelSelection({
        thread_id: threadId,
        selected_flight_id: selectedFlightId,
        selected_hotels: requiredHotelStayKeys.map((stayKey) => ({
          stay_key: stayKey,
          hotel_option_id: selectedHotelIds[stayKey],
        })),
      });
      shouldScrollToUpdatedCost.current = true;
      onTravelSelectionConfirmed?.(
        response.travel_selections,
        response.trip_cost_summary,
      );
      setSelectionMode(false);
    } catch (caughtError) {
      setSelectionError(
        caughtError instanceof Error
          ? caughtError.message
          : "Unable to update the trip cost.",
      );
    } finally {
      setSelectionUpdating(false);
    }
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
      <FlightRecommendations
        idPrefix={idPrefix}
        itinerary={itinerary}
        onSelectFlight={setSelectedFlightId}
        selectedFlightId={selectedFlightId}
        selectionMode={selectionMode}
      />
      <HotelRecommendations
        idPrefix={idPrefix}
        itinerary={itinerary}
        onSelectHotel={(stayKey, hotelOptionId) =>
          setSelectedHotelIds((current) => ({
            ...current,
            [stayKey]: hotelOptionId,
          }))
        }
        selectedHotelIds={selectedHotelIds}
        selectionMode={selectionMode}
      />
      {threadId && selectionMode ? (
        <TravelSelectionWorkflow
          complete={selectionComplete}
          costSummary={tripCostSummary}
          dismissed={selectionDismissed}
          error={selectionError}
          itinerary={itinerary}
          onBegin={beginSelection}
          onCancel={() => {
            setSelectionMode(false);
            setSelectionError(null);
          }}
          onConfirm={confirmSelections}
          onDismiss={() => setSelectionDismissed(true)}
          selections={travelSelections}
          selectionMode
          updatedTripCostSectionId={updatedTripCostSectionId}
          updating={selectionUpdating}
        />
      ) : null}
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
      {threadId && !selectionMode ? (
        <TravelSelectionWorkflow
          complete={selectionComplete}
          costSummary={tripCostSummary}
          dismissed={selectionDismissed}
          error={selectionError}
          itinerary={itinerary}
          onBegin={beginSelection}
          onCancel={() => {
            setSelectionMode(false);
            setSelectionError(null);
          }}
          onConfirm={confirmSelections}
          onDismiss={() => setSelectionDismissed(true)}
          selections={travelSelections}
          selectionMode={false}
          updatedTripCostSectionId={updatedTripCostSectionId}
          updating={selectionUpdating}
        />
      ) : null}
    </div>
  );
}
