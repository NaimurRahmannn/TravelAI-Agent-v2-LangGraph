export type ChatRequest = {
  message: string;
  thread_id?: string | null;
  user_id?: string | null;
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
  provider: "pexels" | "wikimedia_commons";
  provider_image_id?: string | null;
  wikidata_entity_id?: string | null;
  commons_file_title?: string | null;
  original_url: string;
  thumbnail_url?: string | null;
  source_page_url: string;
  width?: number | null;
  height?: number | null;
  author?: string | null;
  author_url?: string | null;
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
  travel_mode_to_next?: TravelMode | null;
  place?: ResolvedPlace | null;
  place_resolution_status: "resolved" | "partially_resolved" | "unresolved";
  image?: PlaceImage | null;
};

export type TravelMode = "walk" | "drive" | "transit" | "bicycle";

export type TravelLeg = {
  provider: "geoapify";
  from_activity_index: number;
  to_activity_index: number;
  from_name: string;
  to_name: string;
  mode: TravelMode;
  distance_meters?: number | null;
  duration_seconds?: number | null;
  status: "resolved" | "unavailable";
};

export type WeatherStatus =
  | "resolved"
  | "outside_forecast_horizon"
  | "unavailable"
  | "skipped";

export type DailyWeather = {
  provider: "openweather";
  date: string;
  condition: string;
  description?: string | null;
  min_temperature_c: number;
  max_temperature_c: number;
  precipitation_probability_pct?: number | null;
  wind_speed_mps?: number | null;
  fetched_at: string;
};

export type ItineraryDay = {
  day_number: number;
  date?: string | null;
  city: string;
  activities: Activity[];
  travel_legs: TravelLeg[];
  estimated_daily_cost_usd?: number | null;
  weather?: DailyWeather | null;
  weather_status: WeatherStatus;
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
};

export type RecommendationStatus =
  | "not_searched"
  | "available"
  | "no_results"
  | "unavailable";

export type RecommendationDomainState = {
  status: RecommendationStatus;
  provider_result_count: number;
};

export type FlightOption = {
  provider: "swoop";
  provider_offer_id: string;
  origin_code: string;
  destination_code: string;
  adults: number;
  total_duration_minutes: number;
  stops: number;
  total_price: number;
  currency: string;
  price_type: "shopping_total";
  airline_names: string[];
  slices: FlightSlice[];
  fetched_at: string;
};

export type FlightSegment = {
  origin_code: string;
  destination_code: string;
  departure_at: string;
  arrival_at: string;
  duration_minutes: number;
  airline_code?: string | null;
  airline_name?: string | null;
  operator_name?: string | null;
  flight_number?: string | null;
  aircraft?: string | null;
};

export type FlightLayover = {
  airport_code?: string | null;
  airport_name?: string | null;
  city?: string | null;
  duration_minutes: number;
  is_overnight: boolean;
};

export type FlightSlice = {
  origin_code: string;
  destination_code: string;
  departure_at: string;
  arrival_at: string;
  duration_minutes: number;
  stops: number;
  segments: FlightSegment[];
  layovers: FlightLayover[];
};

export type HotelOption = {
  provider: string;
  provider_hotel_id: string;
  provider_offer_id: string;
  stay_key: string;
  name: string;
  city?: string | null;
  country?: string | null;
  formatted_address?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  check_in: string;
  check_out: string;
  nights: number;
  total_price: number;
  currency: string;
  price_per_night?: number | null;
  room_name?: string | null;
  board_name?: string | null;
  rating?: number | null;
  review_count?: number | null;
  refundable?: boolean | null;
  taxes_included?: boolean | null;
  image_url?: string | null;
  external_url?: string | null;
  is_sandbox: boolean;
  fetched_at: string;
};

export type SelectedHotelStay = {
  stay_key: string;
  hotel_option_id: string;
};

export type TravelSelections = {
  selected_flight_id: string;
  selected_hotels: SelectedHotelStay[];
};

export type TripCostSummary = {
  base_trip_total_usd: number;
  selected_flight_usd: number;
  selected_hotels_usd: number;
  additions_total_usd: number;
  updated_trip_total_usd: number;
  user_budget_usd?: number | null;
  difference_from_budget_usd?: number | null;
};

export type TravelSelectionRequest = TravelSelections & {
  thread_id: string;
};

export type TravelSelectionResponse = {
  thread_id: string;
  travel_selections: TravelSelections;
  trip_cost_summary: TripCostSummary;
};

export type RestaurantRecommendation = {
  provider: string;
  provider_place_id: string;
  name: string;
  formatted_address?: string | null;
  latitude: number;
  longitude: number;
  categories: string[];
  cuisine: string[];
  distance_meters?: number | null;
  price_level?: string | null;
  external_url?: string | null;
};

export type TravelRecommendations = {
  flights: FlightOption[];
  hotels: HotelOption[];
  restaurants: RestaurantRecommendation[];
  flight_status: RecommendationDomainState;
  hotel_status: RecommendationDomainState;
  restaurant_status: RecommendationDomainState;
};

export type TripPlan = {
  title: string;
  origin?: string | null;
  destination: string;
  start_date?: string | null;
  end_date?: string | null;
  duration_days: number;
  travelers: number;
  guest_nationality_country_code?: string | null;
  summary?: string | null;
  preferences: string[];
  days: ItineraryDay[];
  budget: BudgetBreakdown;
  recommendations?: TravelRecommendations | null;
  practical_notes: string[];
};

export type ChatResponse = {
  response: string;
  thread_id: string;
  itinerary?: TripPlan | null;
  travel_selections?: TravelSelections | null;
  trip_cost_summary?: TripCostSummary | null;
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

export async function confirmTravelSelection(
  request: TravelSelectionRequest,
): Promise<TravelSelectionResponse> {
  const response = await fetch(`${API_BASE_URL}/trip/select-travel`, {
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
