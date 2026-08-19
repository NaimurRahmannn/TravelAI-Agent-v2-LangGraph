import { MarkdownContent } from "@/app/MarkdownContent";
import type { TripPlan } from "@/lib/api";
import { TripItinerary } from "./itinerary/TripItinerary";

type AssistantMessageProps = {
  content: string;
  itinerary?: TripPlan | null;
};

export function AssistantMessage({ content, itinerary }: AssistantMessageProps) {
  if (itinerary) {
    return <TripItinerary itinerary={itinerary} />;
  }
  return <MarkdownContent content={content || "Streaming..."} />;
}
