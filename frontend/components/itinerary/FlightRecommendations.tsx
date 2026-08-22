import { CircleAlert, Clock3, Loader2, Plane, RefreshCcw } from "lucide-react";
import type {
  FlightOption,
  FlightSlice,
  RecommendationStatus,
  TripPlan,
} from "@/lib/api";

type FlightRecommendationsProps = {
  error?: string | null;
  idPrefix: string;
  itinerary: TripPlan;
  onRefresh?: () => Promise<void> | void;
  onSelectFlight?: (flightId: string) => void;
  selectedFlightId?: string | null;
  selectionMode?: boolean;
  refreshing?: boolean;
};

export function FlightRecommendations({
  error,
  idPrefix,
  itinerary,
  onRefresh,
  onSelectFlight,
  selectedFlightId,
  selectionMode = false,
  refreshing = false,
}: FlightRecommendationsProps) {
  const recommendations = itinerary.recommendations;
  if (
    !recommendations ||
    recommendations.flight_status.status === "not_searched"
  ) {
    return null;
  }

  const headingId = `${idPrefix}-flights-heading`;
  const flights = recommendations.flights;

  return (
    <section aria-labelledby={headingId} className="flightRecommendations">
      <header className="flightSectionHeader">
        <span>
          <Plane aria-hidden="true" size={20} />
        </span>
        <div>
          <p>Current flight search</p>
          <h3 id={headingId}>Flight recommendations</h3>
        </div>
        {onRefresh ? (
          <button
            className="flightRefreshButton"
            disabled={refreshing}
            onClick={onRefresh}
            type="button"
          >
            {refreshing ? (
              <Loader2 aria-hidden="true" className="spin" size={15} />
            ) : (
              <RefreshCcw aria-hidden="true" size={15} />
            )}
            {refreshing ? "Refreshing flights..." : "Refresh flights"}
          </button>
        ) : null}
      </header>

      {error ? (
        <p className="flightRefreshError" role="alert">
          <CircleAlert aria-hidden="true" size={16} />
          {error}
        </p>
      ) : null}

      {flights.length > 0 ? (
        <fieldset className="recommendationChoiceGroup">
          <legend className="visuallyHidden">Choose one flight</legend>
          <div className="flightCardGrid">
            {flights.map((flight) => (
              <FlightCard
                flight={flight}
                idPrefix={idPrefix}
                isSelected={selectedFlightId === flight.provider_offer_id}
                key={flight.provider_offer_id}
                onSelect={onSelectFlight}
                selectionMode={selectionMode}
              />
            ))}
          </div>
        </fieldset>
      ) : (
        <FlightEmptyState status={recommendations.flight_status.status} />
      )}

      <div className="flightDisclaimer">
        <p>Flight prices and availability can change.</p>
        <p>Flight search data from Google Flights via Swoop.</p>
      </div>
    </section>
  );
}

function FlightCard({
  flight,
  idPrefix,
  isSelected,
  onSelect,
  selectionMode,
}: {
  flight: FlightOption;
  idPrefix: string;
  isSelected: boolean;
  onSelect?: (flightId: string) => void;
  selectionMode: boolean;
}) {
  const airlines = flight.airline_names.join(" + ") || "Airline unavailable";
  const route = flight.slices
    .map((slice) => `${slice.origin_code} → ${slice.destination_code}`)
    .join(" · ");

  return (
    <article className={`flightCard ${isSelected ? "recommendationSelected" : ""}`}>
      {selectionMode ? (
        <label className="recommendationRadio">
          <input
            checked={isSelected}
            name={`${idPrefix}-flight-selection`}
            onChange={() => onSelect?.(flight.provider_offer_id)}
            type="radio"
            value={flight.provider_offer_id}
          />
          <span>Select this flight</span>
        </label>
      ) : null}
      <header className="flightCardHeader">
        <div>
          <span className="fareEstimateTag">Flight recommendation</span>
          <p className="flightAirline">{airlines}</p>
        </div>
        <p className="flightMarketRoute">{route}</p>
      </header>

      <div className="fareLegs">
        {flight.slices.map((slice, index) => (
          <FlightSliceRow
            index={index}
            key={`${slice.origin_code}-${slice.destination_code}-${index}`}
            slice={slice}
            totalSlices={flight.slices.length}
          />
        ))}
      </div>

      <footer className="flightPricePanel">
        <div>
          <span>
            Total for {flight.adults} {flight.adults === 1 ? "adult" : "adults"}
          </span>
          <strong>{formatMoney(flight.total_price, flight.currency)}</strong>
        </div>
      </footer>
    </article>
  );
}

function FlightSliceRow({
  index,
  slice,
  totalSlices,
}: {
  index: number;
  slice: FlightSlice;
  totalSlices: number;
}) {
  const label =
    totalSlices === 2 ? (index === 0 ? "Outbound" : "Return") : `Leg ${index + 1}`;
  const segmentAirlines = Array.from(
    new Set(
      slice.segments
        .map((segment) => segment.airline_name || segment.operator_name)
        .filter((name): name is string => Boolean(name)),
    ),
  );
  const flightNumbers = slice.segments
    .map((segment) =>
      segment.flight_number
        ? `${segment.airline_code ? `${segment.airline_code} ` : ""}${segment.flight_number}`
        : null,
    )
    .filter((number): number is string => Boolean(number));

  return (
    <div className="fareLeg">
      <div className="fareLegIdentity">
        <span>{label}</span>
        <small>{formatFlightDate(slice.departure_at)}</small>
      </div>
      <div className="fareLegRoute">
        <div>
          <strong>{slice.origin_code}</strong>
          <small>{formatFlightTime(slice.departure_at)}</small>
        </div>
        <span>→</span>
        <div>
          <strong>{slice.destination_code}</strong>
          <small>{formatFlightTime(slice.arrival_at)}</small>
        </div>
      </div>
      <div className="fareLegFacts">
        <span>
          <Clock3 aria-hidden="true" size={13} />
          {formatDuration(slice.duration_minutes)}
        </span>
        <span>{formatStops(slice.stops)}</span>
        {segmentAirlines.length > 0 ? <span>{segmentAirlines.join(" + ")}</span> : null}
        {flightNumbers.length > 0 ? <span>{flightNumbers.join(" / ")}</span> : null}
      </div>
    </div>
  );
}

function FlightEmptyState({ status }: { status: RecommendationStatus }) {
  const copy: Record<RecommendationStatus, string> = {
    not_searched: "Flight search was not requested.",
    available: "Flight recommendations are available.",
    no_results:
      "No matching flight results were found for these dates and route.",
    unavailable: "Flight search is temporarily unavailable.",
  };

  return (
    <div className="flightEmptyState">
      <CircleAlert aria-hidden="true" size={19} />
      <p>{copy[status]}</p>
    </div>
  );
}

function formatMoney(amount: number, currency: string): string {
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    }).format(amount);
  } catch {
    return `${currency} ${amount.toFixed(2)}`;
  }
}

function formatFlightDate(value: string): string {
  const datePart = value.slice(0, 10);
  const date = new Date(`${datePart}T00:00:00`);
  if (Number.isNaN(date.getTime())) {
    return datePart;
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
  }).format(date);
}

function formatFlightTime(value: string): string {
  const match = value.match(/T(\d{2}):(\d{2})/);
  if (!match) {
    return "--:--";
  }
  const hours = Number(match[1]);
  const suffix = hours >= 12 ? "PM" : "AM";
  return `${hours % 12 || 12}:${match[2]} ${suffix}`;
}

function formatDuration(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  if (hours === 0) {
    return `${remainder}m`;
  }
  return remainder === 0 ? `${hours}h` : `${hours}h ${remainder}m`;
}

function formatStops(stops: number): string {
  if (stops === 0) {
    return "Nonstop";
  }
  return `${stops} ${stops === 1 ? "stop" : "stops"}`;
}
