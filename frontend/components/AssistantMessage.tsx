import { MarkdownContent } from "@/app/MarkdownContent";
import { useState } from "react";
import type {
  ChatResponseMode,
  ConfirmedTripSnapshot,
  DetailedRoutingPlan,
  FlightSearchScope,
  SelectionStatus,
  TravelSelections,
  TripCostSummary,
  TripPlan,
} from "@/lib/api";
import { TripItinerary } from "./itinerary/TripItinerary";
import { FlightRecommendations } from "./itinerary/FlightRecommendations";
import { HotelRecommendations } from "./itinerary/HotelRecommendations";
import { TravelDatePicker } from "./TravelDatePicker";

type AssistantMessageProps = {
  content: string;
  responseMode?: ChatResponseMode;
  flightSearchScope?: FlightSearchScope | null;
  itinerary?: TripPlan | null;
  missingFields?: string[];
  isLoading?: boolean;
  mapPortalTarget?: HTMLElement | null;
  onDateContinue?: (startDate: string, endDate: string) => Promise<void> | void;
  onDateUpdate?: (startDate: string, endDate: string) => Promise<void> | void;
  onTravelSelectionConfirmed?: (
    selections: TravelSelections,
    costSummary: TripCostSummary,
    confirmedSnapshot: ConfirmedTripSnapshot,
  ) => void;
  onDetailedRoutingGenerated?: (plan: DetailedRoutingPlan) => void;
  onFlightsRefreshed?: (itinerary: TripPlan) => void;
  onFlightLegSelected?: (
    scope: "outbound" | "return",
    flightId: string,
  ) => Promise<void> | void;
  showMap?: boolean;
  threadId?: string | null;
  travelSelections?: TravelSelections | null;
  tripCostSummary?: TripCostSummary | null;
  detailedRoutingPlan?: DetailedRoutingPlan | null;
  flightSelectionStatus?: SelectionStatus;
  hotelSelectionStatus?: SelectionStatus;
};

export function AssistantMessage({
  content,
  detailedRoutingPlan,
  flightSearchScope,
  flightSelectionStatus,
  hotelSelectionStatus,
  itinerary,
  missingFields = [],
  isLoading = false,
  mapPortalTarget,
  onDateContinue,
  onDateUpdate,
  onDetailedRoutingGenerated,
  onFlightsRefreshed,
  onFlightLegSelected,
  onTravelSelectionConfirmed,
  responseMode = "text",
  showMap = true,
  threadId,
  travelSelections,
  tripCostSummary,
}: AssistantMessageProps) {
  const [focusedFlightId, setFocusedFlightId] = useState<string | null>(null);
  const [focusedFlightError, setFocusedFlightError] = useState<string | null>(
    null,
  );
  if (responseMode === "flight_suggestions") {
    if (itinerary) {
      return (
        <FlightRecommendations
          idPrefix={`focused-${itinerary.destination.replace(/\s+/g, "-").toLowerCase()}`}
          itinerary={itinerary}
          error={focusedFlightError}
          onSelectFlight={
            onFlightLegSelected && flightSearchScope !== "round_trip"
              ? async (flightId) => {
                  setFocusedFlightId(flightId);
                  setFocusedFlightError(null);
                  try {
                    await onFlightLegSelected(
                      flightSearchScope ?? "return",
                      flightId,
                    );
                  } catch (caughtError) {
                    setFocusedFlightError(
                      caughtError instanceof Error
                        ? caughtError.message
                        : "Unable to select this flight.",
                    );
                  }
                }
              : undefined
          }
          scope={flightSearchScope ?? "round_trip"}
          selectedFlightId={focusedFlightId}
          selectionMode={Boolean(
            onFlightLegSelected && flightSearchScope !== "round_trip",
          )}
          variant="standalone"
        />
      );
    }
    return (
      <div className="assistantResponse">
        <MarkdownContent content={content} />
      </div>
    );
  }

  if (responseMode === "hotel_suggestions") {
    if (
      itinerary &&
      itinerary.recommendations?.hotel_status.status !== "not_searched"
    ) {
      return (
        <HotelRecommendations
          idPrefix={`focused-${itinerary.destination.replace(/\s+/g, "-").toLowerCase()}`}
          itinerary={itinerary}
        />
      );
    }
    return (
      <div className="assistantResponse">
        <MarkdownContent content={content} />
      </div>
    );
  }

  if (
    itinerary &&
    (responseMode === "itinerary" || responseMode === "trip_extension")
  ) {
    return (
      <TripItinerary
        detailedRoutingPlan={detailedRoutingPlan}
        flightSelectionStatus={flightSelectionStatus}
        hotelSelectionStatus={hotelSelectionStatus}
        isUpdatingDates={isLoading}
        itinerary={itinerary}
        mapPortalTarget={mapPortalTarget}
        onDateUpdate={onDateUpdate}
        onDetailedRoutingGenerated={onDetailedRoutingGenerated}
        onFlightsRefreshed={onFlightsRefreshed}
        onTravelSelectionConfirmed={onTravelSelectionConfirmed}
        showMap={showMap}
        threadId={threadId}
        travelSelections={travelSelections}
        tripCostSummary={tripCostSummary}
      />
    );
  }

  const needsDates =
    missingFields.includes("dates") && onDateContinue !== undefined;
  if (needsDates) {
    return (
      <TravelDatePicker disabled={isLoading} onContinue={onDateContinue} />
    );
  }

  return (
    <div className="assistantResponse">
      <MarkdownContent content={content} />
    </div>
  );
}
