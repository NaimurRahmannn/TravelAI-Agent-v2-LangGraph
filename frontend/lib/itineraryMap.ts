import type { TripPlan } from "./api";

export type ItineraryMapPoint = {
  id: string;
  dayNumber: number;
  activityIndex: number;
  sequence: number;
  name: string;
  city: string;
  latitude: number;
  longitude: number;
  providerPlaceId: string;
  activityDomId: string;
};

export function buildActivityDomId(
  idPrefix: string,
  dayNumber: number,
  activityIndex: number,
): string {
  return `${idPrefix}-day-${dayNumber}-activity-${activityIndex + 1}`;
}

export function buildItineraryMapPoints(
  itinerary: TripPlan,
  idPrefix: string,
): ItineraryMapPoint[] {
  const points: ItineraryMapPoint[] = [];

  for (const day of itinerary.days) {
    day.activities.forEach((activity, activityIndex) => {
      const place = activity.place;
      if (
        place?.resolution_status !== "resolved" ||
        !isValidCoordinate(place.latitude, 90) ||
        !isValidCoordinate(place.longitude, 180)
      ) {
        return;
      }

      const activityDomId = buildActivityDomId(
        idPrefix,
        day.day_number,
        activityIndex,
      );
      points.push({
        id: `${activityDomId}-${place.provider_place_id}`,
        dayNumber: day.day_number,
        activityIndex,
        sequence: points.length + 1,
        name: activity.name,
        city: day.city,
        latitude: place.latitude,
        longitude: place.longitude,
        providerPlaceId: place.provider_place_id,
        activityDomId,
      });
    });
  }

  return points;
}

function isValidCoordinate(value: unknown, maximum: number): value is number {
  return (
    typeof value === "number" &&
    Number.isFinite(value) &&
    value >= -maximum &&
    value <= maximum
  );
}
