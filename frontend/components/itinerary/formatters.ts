import type { Activity } from "@/lib/api";

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

export function isTrustedWikimediaImageUrl(value: string | null | undefined): boolean {
  if (!value) {
    return false;
  }
  try {
    const url = new URL(value);
    return (
      url.protocol === "https:" &&
      url.hostname === "upload.wikimedia.org" &&
      url.username === "" &&
      url.password === ""
    );
  } catch {
    return false;
  }
}

export function trustedWikimediaImageUrl(
  thumbnailUrl: string | null | undefined,
  originalUrl: string | null | undefined,
): string | null {
  if (isTrustedWikimediaImageUrl(thumbnailUrl)) {
    return thumbnailUrl ?? null;
  }
  return isTrustedWikimediaImageUrl(originalUrl) ? originalUrl ?? null : null;
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
