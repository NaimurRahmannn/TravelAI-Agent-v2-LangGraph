import { MarkdownContent } from "@/app/MarkdownContent";
import type {
  DetailedRoutingPlan,
  SelectionStatus,
  TravelSelections,
  TripCostSummary,
  TripPlan,
} from "@/lib/api";
import { TripItinerary } from "./itinerary/TripItinerary";
import { TravelDatePicker } from "./TravelDatePicker";

type AssistantMessageProps = {
  content: string;
  itinerary?: TripPlan | null;
  missingFields?: string[];
  isLoading?: boolean;
  mapPortalTarget?: HTMLElement | null;
  onDateContinue?: (startDate: string, endDate: string) => Promise<void> | void;
  onDateUpdate?: (startDate: string, endDate: string) => Promise<void> | void;
  onTravelSelectionConfirmed?: (
    selections: TravelSelections,
    costSummary: TripCostSummary,
  ) => void;
  onDetailedRoutingGenerated?: (plan: DetailedRoutingPlan) => void;
  onFlightsRefreshed?: (itinerary: TripPlan) => void;
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
  onTravelSelectionConfirmed,
  showMap = true,
  threadId,
  travelSelections,
  tripCostSummary,
}: AssistantMessageProps) {
  if (itinerary) {
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
