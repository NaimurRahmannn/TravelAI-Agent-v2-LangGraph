import {
  BadgeCheck,
  CircleAlert,
  Clock3,
  FlaskConical,
  Plane,
} from "lucide-react";
import type {
  FlightOption,
  FlightSlice,
  RecommendationStatus,
  TripPlan,
} from "@/lib/api";
import { formatUsd } from "./formatters";

type FlightRecommendationsProps = {
  idPrefix: string;
  itinerary: TripPlan;
};

export function FlightRecommendations({
  idPrefix,
  itinerary,
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
          <p>Provider-backed options</p>
          <h3 id={headingId}>Flight recommendations</h3>
        </div>
      </header>

      {flights.length > 0 ? (
        <div className="flightCardGrid">
          {flights.map((flight) => (
            <FlightCard
              flight={flight}
              key={flight.provider_offer_id}
              travelers={itinerary.travelers}
              userBudget={itinerary.budget.user_budget_usd}
            />
          ))}
        </div>
      ) : (
        <FlightEmptyState
          status={recommendations.flight_status.status}
        />
      )}

      <p className="flightDisclaimer">
        Flight prices can change. Optional extras may cost more.
      </p>
    </section>
  );
}

function FlightCard({
  flight,
  travelers,
  userBudget,
}: {
  flight: FlightOption;
  travelers: number;
  userBudget?: number | null;
}) {
  const carrierNames = Array.from(
    new Set(
      flight.slices.flatMap((slice) =>
        slice.segments.map((segment) => segment.operating_carrier_name),
      ),
    ),
  );
  const projectedTotal = flight.budget_evaluation?.projected_trip_total_usd;

  return (
    <article className="flightCard">
      <header className="flightCardHeader">
        <div>
          <p className="flightAirline">
            {flight.airline_name || carrierNames[0] || "Flight option"}
          </p>
          {carrierNames.length > 0 ? (
            <p className="flightOperators">
              Operated by {carrierNames.join(", ")}
            </p>
          ) : null}
        </div>
        {flight.live_data === false ? (
          <span className="testFlightBadge">
            <FlaskConical aria-hidden="true" size={14} />
            Test flight data
          </span>
        ) : null}
      </header>

      <div className="flightSlices">
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
            Total for {travelers} {travelers === 1 ? "adult" : "adults"}
          </span>
          <strong>{formatMoney(flight.total_price, flight.currency)}</strong>
        </div>
        {projectedTotal != null ? (
          <div>
            <span>Projected trip total</span>
            <strong>{formatUsd(projectedTotal)}</strong>
          </div>
        ) : null}
        {flight.budget_evaluation?.status === "within_budget" &&
        userBudget != null ? (
          <p className="flightBudgetFit">
            <BadgeCheck aria-hidden="true" size={17} />
            Within your {formatUsd(userBudget)} trip budget
          </p>
        ) : null}
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
  const firstSegment = slice.segments[0];
  const lastSegment = slice.segments[slice.segments.length - 1];
  const label =
    totalSlices === 2 ? (index === 0 ? "Outbound" : "Return") : `Leg ${index + 1}`;

  return (
    <div className="flightSlice">
      <div className="flightSliceLabel">
        <span>{label}</span>
        <small>{formatFlightDate(firstSegment?.departure_at)}</small>
      </div>
      <div className="flightRouteTimes">
        <div>
          <strong>{slice.origin_code}</strong>
          <span>{formatFlightTime(firstSegment?.departure_at)}</span>
        </div>
        <div className="flightDurationLine">
          <Clock3 aria-hidden="true" size={13} />
          <span>{formatDuration(slice.duration_minutes)}</span>
        </div>
        <div>
          <strong>{slice.destination_code}</strong>
          <span>{formatFlightTime(lastSegment?.arrival_at)}</span>
        </div>
      </div>
      <p className="flightStops">
        {slice.stops === 0
          ? "Nonstop"
          : `${slice.stops} ${slice.stops === 1 ? "stop" : "stops"}`}
      </p>
    </div>
  );
}

function FlightEmptyState({ status }: { status: RecommendationStatus }) {
  const copy: Record<RecommendationStatus, string> = {
    not_searched: "Flight search was not requested.",
    available: "Flight recommendations are available.",
    no_results: "No flight offers were found for these dates and cities.",
    no_affordable_results:
      "No returned flight offers fit within the current trip budget.",
    budget_unverified:
      "Flight offers were found, but their budget fit could not be verified without currency conversion.",
    unavailable: "Flight recommendations are unavailable right now.",
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

function formatFlightDate(value: string | undefined): string {
  const datePart = value?.slice(0, 10);
  if (!datePart) {
    return "Date unavailable";
  }
  const date = new Date(`${datePart}T00:00:00`);
  if (Number.isNaN(date.getTime())) {
    return datePart;
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
  }).format(date);
}

function formatFlightTime(value: string | undefined): string {
  const match = value?.match(/T(\d{2}):(\d{2})/);
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
