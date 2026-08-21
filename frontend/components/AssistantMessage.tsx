import { MarkdownContent } from "@/app/MarkdownContent";
import type {
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
  showMap?: boolean;
  threadId?: string | null;
  travelSelections?: TravelSelections | null;
  tripCostSummary?: TripCostSummary | null;
};

export function AssistantMessage({
  content,
  itinerary,
  missingFields = [],
  isLoading = false,
  mapPortalTarget,
  onDateContinue,
  onDateUpdate,
  onTravelSelectionConfirmed,
  showMap = true,
  threadId,
  travelSelections,
  tripCostSummary,
}: AssistantMessageProps) {
  if (itinerary) {
    return (
      <TripItinerary
        isUpdatingDates={isLoading}
        itinerary={itinerary}
        mapPortalTarget={mapPortalTarget}
        onDateUpdate={onDateUpdate}
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
