import { Clock3, MapPin, MapPinned, Sparkles, WalletCards } from "lucide-react";
import type { Activity } from "@/lib/api";
import { ActivityImage } from "./ActivityImage";
import {
  formatActivityCategory,
  formatActivityTime,
  formatPlaceAddress,
  formatUsd,
  trustedWikimediaImageUrl,
} from "./formatters";

type ActivityCardProps = {
  activity: Activity;
  activityDomId: string;
  isMapSelected: boolean;
  mapPointId?: string;
  mapReady: boolean;
  onShowOnMap: (pointId: string) => void;
};

export function ActivityCard({
  activity,
  activityDomId,
  isMapSelected,
  mapPointId,
  mapReady,
  onShowOnMap,
}: ActivityCardProps) {
  const resolvedPlace = activity.place?.resolution_status === "resolved";
  const trustedImage = activity.image
    ? trustedWikimediaImageUrl(
        activity.image.thumbnail_url,
        activity.image.original_url,
      )
    : null;
  const address = formatPlaceAddress(activity);
  const time = formatActivityTime(activity);
  const compact = !resolvedPlace;

  return (
    <article
      className={`activityCard ${compact ? "activityCompact" : "activityPlace"} ${
        trustedImage ? "activityWithImage" : "activityWithoutImage"
      } ${isMapSelected ? "activityMapSelected" : ""}`}
      id={activityDomId}
    >
      {trustedImage && activity.image ? (
        <ActivityImage activityName={activity.name} image={activity.image} />
      ) : null}

      <div className="activityContent">
        <header className="activityHeader">
          <div>
            <span className="categoryPill">
              {formatActivityCategory(activity.category)}
            </span>
            <h4>{activity.name}</h4>
          </div>
          {time ? (
            <div className="activityMeta activityTime">
              <Clock3 aria-hidden="true" size={15} />
              <time>{time}</time>
            </div>
          ) : null}
        </header>

        {activity.description ? (
          <p className="activityDescription">{activity.description}</p>
        ) : null}

        {address ? (
          <div className="activityMeta activityAddress">
            <MapPin aria-hidden="true" size={16} />
            <span>{address}</span>
          </div>
        ) : null}

        {activity.reason_for_recommendation ? (
          <div className="recommendation">
            <div>
              <Sparkles aria-hidden="true" size={15} />
              <strong>Why this fits your trip</strong>
            </div>
            <p>{activity.reason_for_recommendation}</p>
          </div>
        ) : null}

        {activity.estimated_cost_usd != null ? (
          <div className="activityMeta activityCost">
            <WalletCards aria-hidden="true" size={16} />
            <span>Estimated cost: {formatUsd(activity.estimated_cost_usd)}</span>
          </div>
        ) : null}

        {mapReady && mapPointId ? (
          <button
            aria-pressed={isMapSelected}
            className="activityMapAction"
            onClick={() => onShowOnMap(mapPointId)}
            type="button"
          >
            <MapPinned aria-hidden="true" size={15} />
            {isMapSelected ? "Shown on map" : "Show on map"}
          </button>
        ) : null}
      </div>
    </article>
  );
}
