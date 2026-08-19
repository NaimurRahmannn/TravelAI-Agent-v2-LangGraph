export type StreamMode = "updates" | "messages" | "debug";

export type ChatRequest = {
  message: string;
  thread_id?: string | null;
  user_id?: string | null;
  stream_mode?: StreamMode;
  start_date?: string;
  end_date?: string;
};

export type ResolvedPlace = {
  provider: "geoapify";
  provider_place_id: string;
  wikidata_entity_id?: string | null;
  name: string;
  formatted_address?: string | null;
  city?: string | null;
  state?: string | null;
  country?: string | null;
  country_code?: string | null;
  latitude: number;
  longitude: number;
  categories: string[];
  confidence?: number | null;
  resolution_status: "resolved" | "partially_resolved";
  source_attribution?: string | null;
};

export type PlaceImage = {
  provider: "wikimedia_commons";
  wikidata_entity_id?: string | null;
  commons_file_title: string;
  original_url: string;
  thumbnail_url?: string | null;
  source_page_url: string;
  width?: number | null;
  height?: number | null;
  author?: string | null;
  credit?: string | null;
  license_short_name: string;
  license_url?: string | null;
  usage_terms?: string | null;
  attribution_text: string;
  description?: string | null;
};

export type Activity = {
  name: string;
  place_search_name?: string | null;
  category: string;
  location_hint?: string | null;
  description?: string | null;
  start_time?: string | null;
  end_time?: string | null;
  estimated_cost_usd?: number | null;
  reason_for_recommendation?: string | null;
  place?: ResolvedPlace | null;
  place_resolution_status: "resolved" | "partially_resolved" | "unresolved";
  image?: PlaceImage | null;
};

export type ItineraryDay = {
  day_number: number;
  date?: string | null;
  city: string;
  activities: Activity[];
  estimated_daily_cost_usd?: number | null;
};

export type BudgetItem = {
  category: string;
  amount_usd: number;
  note?: string | null;
};

export type BudgetBreakdown = {
  items: BudgetItem[];
  estimated_total_usd: number;
  user_budget_usd?: number | null;
  within_budget?: boolean | null;
  international_travel_included?: boolean | null;
};

export type TripPlan = {
  title: string;
  origin?: string | null;
  destination: string;
  start_date?: string | null;
  end_date?: string | null;
  duration_days: number;
  travelers: number;
  summary?: string | null;
  preferences: string[];
  days: ItineraryDay[];
  budget: BudgetBreakdown;
  practical_notes: string[];
};

export type ChatResponse = {
  response: string;
  thread_id: string;
  itinerary?: TripPlan | null;
  missing_fields: string[];
};

export type ApprovalResponse = {
  status: string;
  thread_id: string;
};

export type MapsConfig = {
  enabled: boolean;
  api_key?: string | null;
};

export type StreamEvent = {
  event_type: string;
  node: string;
  content: string;
  thread_id: string;
  timestamp: string;
  itinerary?: TripPlan | null;
  missing_fields?: string[];
};

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

let mapsConfigPromise: Promise<MapsConfig> | null = null;

export function getMapsConfig(): Promise<MapsConfig> {
  if (mapsConfigPromise === null) {
    mapsConfigPromise = fetchMapsConfig().catch((error: unknown) => {
      mapsConfigPromise = null;
      throw error;
    });
  }

  return mapsConfigPromise;
}

async function fetchMapsConfig(): Promise<MapsConfig> {
  const response = await fetch(`${API_BASE_URL}/config/maps`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error("Map configuration is unavailable.");
  }
  return response.json() as Promise<MapsConfig>;
}

export async function sendChat(request: ChatRequest): Promise<ChatResponse> {
  const response = await fetch(`${API_BASE_URL}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error(await getErrorMessage(response));
  }

  return response.json();
}

export async function approveAction(
  threadId: string,
  approved: boolean,
): Promise<ApprovalResponse> {
  const response = await fetch(`${API_BASE_URL}/chat/approve`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      thread_id: threadId,
      approved,
    }),
  });

  if (!response.ok) {
    throw new Error(await getErrorMessage(response));
  }

  return response.json();
}

export async function streamChat(
  request: ChatRequest,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(request),
  });

  if (!response.ok || response.body === null) {
    throw new Error(await getErrorMessage(response));
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();

    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";

    for (const rawEvent of events) {
      const parsedEvent = parseServerSentEvent(rawEvent);
      if (parsedEvent !== null) {
        onEvent(parsedEvent);
      }
    }
  }
}

function parseServerSentEvent(rawEvent: string): StreamEvent | null {
  const dataLine = rawEvent
    .split("\n")
    .find((line) => line.startsWith("data: "));

  if (!dataLine) {
    return null;
  }

  try {
    return JSON.parse(dataLine.slice(6)) as StreamEvent;
  } catch {
    return null;
  }
}

async function getErrorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as {
      detail?: string | Array<{ msg?: string }>;
    };
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
    if (Array.isArray(payload.detail)) {
      const messages = payload.detail
        .map((detail) => detail.msg)
        .filter((message): message is string => Boolean(message));
      if (messages.length > 0) {
        return messages.join(" ");
      }
    }
    return response.statusText;
  } catch {
    return response.statusText;
  }
}
