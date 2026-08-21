import type { Activity, TravelMode } from "@/lib/api";

const usdFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});

export function formatUsd(value: number): string {
  return usdFormatter.format(value);
}

export function formatActivityCategory(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

export function formatActivityTime(activity: Activity): string | null {
  const start = cleanText(activity.start_time);
  const end = cleanText(activity.end_time);
  if (start && end) {
    return `${start} - ${end}`;
  }
  return start || end;
}

export function formatPlaceAddress(activity: Activity): string | null {
  const formatted = cleanText(activity.place?.formatted_address);
  if (formatted) {
    return formatted;
  }

  const locality = [activity.place?.city, activity.place?.country]
    .map(cleanText)
    .filter((value): value is string => Boolean(value));
  if (locality.length > 0) {
    return Array.from(new Set(locality)).join(", ");
  }
  return cleanText(activity.location_hint);
}

export function formatItineraryDate(value: string | null | undefined): string | null {
  const clean = cleanText(value);
  if (!clean) {
    return null;
  }
  const date = new Date(`${clean}T00:00:00`);
  if (Number.isNaN(date.getTime())) {
    return clean;
  }
  return new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  }).format(date);
}

export function formatTravelMode(mode: TravelMode): string {
  return mode === "bicycle"
    ? "Cycle"
    : mode.charAt(0).toUpperCase() + mode.slice(1);
}

export function formatTravelDuration(seconds: number): string {
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) {
    return `${minutes} min`;
  }
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes === 0
    ? `${hours} hr`
    : `${hours} hr ${remainingMinutes} min`;
}

export function formatTravelDistance(meters: number): string {
  if (meters < 1000) {
    return `${Math.round(meters / 10) * 10} m`;
  }
  const kilometers = meters / 1000;
  return `${kilometers < 10 ? kilometers.toFixed(1) : Math.round(kilometers)} km`;
}

export function isTrustedPlaceImageUrl(
  provider: "pexels" | "wikimedia_commons",
  value: string | null | undefined,
): boolean {
  if (!value) {
    return false;
  }
  try {
    const url = new URL(value);
    return (
      url.protocol === "https:" &&
      ((provider === "pexels" && url.hostname === "images.pexels.com") ||
        (provider === "wikimedia_commons" &&
          url.hostname === "upload.wikimedia.org")) &&
      url.username === "" &&
      url.password === ""
    );
  } catch {
    return false;
  }
}

export function trustedPlaceImageUrl(
  provider: "pexels" | "wikimedia_commons",
  thumbnailUrl: string | null | undefined,
  originalUrl: string | null | undefined,
): string | null {
  if (isTrustedPlaceImageUrl(provider, thumbnailUrl)) {
    return thumbnailUrl ?? null;
  }
  return isTrustedPlaceImageUrl(provider, originalUrl)
    ? originalUrl ?? null
    : null;
}

export function isSafeExternalUrl(value: string | null | undefined): boolean {
  if (!value) {
    return false;
  }
  try {
    const url = new URL(value);
    return (
      url.protocol === "https:" && url.username === "" && url.password === ""
    );
  } catch {
    return false;
  }
}

function cleanText(value: string | null | undefined): string | null {
  const clean = value?.trim();
  return clean || null;
}
