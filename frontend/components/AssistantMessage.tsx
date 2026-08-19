import { MarkdownContent } from "@/app/MarkdownContent";
import type { TripPlan } from "@/lib/api";
import { TripItinerary } from "./itinerary/TripItinerary";
import { TravelDatePicker } from "./TravelDatePicker";

type AssistantMessageProps = {
  content: string;
  itinerary?: TripPlan | null;
  missingFields?: string[];
  isLoading?: boolean;
  onDateContinue?: (startDate: string, endDate: string) => Promise<void> | void;
  onDateUpdate?: (startDate: string, endDate: string) => Promise<void> | void;
};

export function AssistantMessage({
  content,
  itinerary,
  missingFields = [],
  isLoading = false,
  onDateContinue,
  onDateUpdate,
}: AssistantMessageProps) {
  if (itinerary) {
    return (
      <TripItinerary
        isUpdatingDates={isLoading}
        itinerary={itinerary}
        onDateUpdate={onDateUpdate}
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
      <MarkdownContent content={content || "Streaming..."} />
    </div>
  );
}
