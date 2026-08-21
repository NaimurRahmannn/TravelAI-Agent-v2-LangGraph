import { Building2, CheckCircle2, CircleAlert, Plane } from "lucide-react";
import type {
  HotelOption,
  TravelSelections,
  TripCostSummary,
  TripPlan,
} from "@/lib/api";

type TravelSelectionWorkflowProps = {
  complete: boolean;
  costSummary?: TripCostSummary | null;
  dismissed: boolean;
  error: string | null;
  itinerary: TripPlan;
  onBegin: () => void;
  onCancel: () => void;
  onConfirm: () => Promise<void> | void;
  onDismiss: () => void;
  selections?: TravelSelections | null;
  selectionMode: boolean;
  updatedTripCostSectionId: string;
  updating: boolean;
};

export function TravelSelectionWorkflow({
  complete,
  costSummary,
  dismissed,
  error,
  itinerary,
  onBegin,
  onCancel,
  onConfirm,
  onDismiss,
  selections,
  selectionMode,
  updatedTripCostSectionId,
  updating,
}: TravelSelectionWorkflowProps) {
  if (!canOfferTravelSelection(itinerary)) {
    return null;
  }

  if (selectionMode) {
    return (
      <section
        aria-labelledby="travel-selection-heading"
        className="travelSelectionPanel"
      >
        <div>
          <p className="selectionEyebrow">Selected travel</p>
          <h3 id="travel-selection-heading">
            Here are the recommendations from your trip plan. Choose one flight
            and one hotel for each stay.
          </h3>
          <p>Prices and availability can change. This does not book anything.</p>
        </div>
        {error ? (
          <p className="travelSelectionError" role="alert">
            <CircleAlert aria-hidden="true" size={17} />
            {error}
          </p>
        ) : null}
        <div className="travelSelectionActions">
          <button
            disabled={!complete || updating}
            onClick={onConfirm}
            type="button"
          >
            {updating ? "Updating trip cost..." : "Confirm selections"}
          </button>
          <button disabled={updating} onClick={onCancel} type="button">
            Cancel
          </button>
        </div>
      </section>
    );
  }

  if (selections && costSummary) {
    return (
      <ConfirmedTravelSelection
        costSummary={costSummary}
        itinerary={itinerary}
        onChange={onBegin}
        selections={selections}
        sectionId={updatedTripCostSectionId}
      />
    );
  }

  if (dismissed) {
    return null;
  }

  return (
    <section
      aria-labelledby="travel-selection-prompt"
      className="travelSelectionPrompt"
    >
      <div>
        <p className="selectionEyebrow">Complete your estimate</p>
        <h3 id="travel-selection-prompt">
          Would you like to select a flight and hotel and include them in your
          total trip cost?
        </h3>
        <p>Selection uses the recommendations already shown above.</p>
      </div>
      <div className="travelSelectionActions">
        <button onClick={onBegin} type="button">
          Select flight &amp; hotel
        </button>
        <button onClick={onDismiss} type="button">
          Not now
        </button>
      </div>
    </section>
  );
}

function ConfirmedTravelSelection({
  costSummary,
  itinerary,
  onChange,
  sectionId,
  selections,
}: {
  costSummary: TripCostSummary;
  itinerary: TripPlan;
  onChange: () => void;
  sectionId: string;
  selections: TravelSelections;
}) {
  const recommendations = itinerary.recommendations;
  const flight = recommendations?.flights.find(
    (option) => option.provider_offer_id === selections.selected_flight_id,
  );
  const hotels = selections.selected_hotels
    .map((selection) =>
      recommendations?.hotels.find(
        (option) =>
          option.provider_offer_id === selection.hotel_option_id &&
          option.stay_key === selection.stay_key,
      ),
    )
    .filter((option): option is HotelOption => Boolean(option));

  return (
    <section
      aria-labelledby={`${sectionId}-heading`}
      className="travelSelectionPanel confirmedTravelSelection"
      id={sectionId}
    >
      <header>
        <CheckCircle2 aria-hidden="true" size={22} />
        <div>
          <p className="selectionEyebrow">Selected for trip estimate</p>
          <h3 id={`${sectionId}-heading`} tabIndex={-1}>
            Updated Trip Cost
          </h3>
        </div>
      </header>

      <div className="selectedTravelChoices">
        {flight ? (
          <article>
            <Plane aria-hidden="true" size={18} />
            <div>
              <strong>{flight.airline_names.join(" + ") || "Selected flight"}</strong>
              <span>
                {flight.origin_code} to {flight.destination_code} ·{" "}
                {formatMoney(flight.total_price)}
              </span>
            </div>
          </article>
        ) : null}
        {hotels.map((hotel) => (
          <article key={hotel.stay_key}>
            <Building2 aria-hidden="true" size={18} />
            <div>
              <strong>{hotel.name}</strong>
              <span>
                {hotel.city || "Hotel stay"} · {hotel.check_in} to {hotel.check_out}
                {" · "}
                {formatMoney(hotel.total_price)} total stay
              </span>
            </div>
          </article>
        ))}
      </div>

      <dl className="tripCostRows">
        <CostRow label="Base Trip Estimate" value={costSummary.base_trip_total_usd} />
        <CostRow label="Selected flight" value={costSummary.selected_flight_usd} />
        <CostRow label="Selected hotels" value={costSummary.selected_hotels_usd} />
        <CostRow label="Travel additions" value={costSummary.additions_total_usd} />
        <div className="updatedTripTotalRow">
          <dt>Updated Trip Total</dt>
          <dd>{formatMoney(costSummary.updated_trip_total_usd)}</dd>
        </div>
        {costSummary.user_budget_usd != null ? (
          <CostRow
            label="Original target budget"
            value={costSummary.user_budget_usd}
          />
        ) : null}
      </dl>

      {budgetComparison(costSummary) ? (
        <p className="tripCostComparison">{budgetComparison(costSummary)}</p>
      ) : null}
      <p className="selectionBookingNote">
        Selected for trip-cost planning only. No reservation or purchase has
        been made.
      </p>
      <button className="changeSelectionsButton" onClick={onChange} type="button">
        Change selection
      </button>
    </section>
  );
}

function CostRow({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{formatMoney(value)}</dd>
    </div>
  );
}

export function getSelectableHotelStayKeys(itinerary: TripPlan): string[] {
  const hotels = itinerary.recommendations?.hotels ?? [];
  const requiredStays = new Set(deriveRequiredHotelStays(itinerary));
  return Array.from(
    new Set(
      hotels
        .filter((hotel) =>
          requiredStays.has(
            `${normalizeCity(hotel.city)}|${hotel.check_in}|${hotel.check_out}`,
          ),
        )
        .map((hotel) => hotel.stay_key),
    ),
  );
}

function canOfferTravelSelection(itinerary: TripPlan): boolean {
  const recommendations = itinerary.recommendations;
  if (
    !recommendations ||
    recommendations.flight_status.status !== "available" ||
    recommendations.hotel_status.status !== "available" ||
    recommendations.flights.length === 0 ||
    recommendations.hotels.length === 0
  ) {
    return false;
  }

  const requiredStays = deriveRequiredHotelStays(itinerary);
  const hotelStays = new Set(
    recommendations.hotels.map(
      (hotel) =>
        `${normalizeCity(hotel.city)}|${hotel.check_in}|${hotel.check_out}`,
    ),
  );
  return (
    requiredStays.length > 0 &&
    requiredStays.every((stay) => hotelStays.has(stay))
  );
}

function deriveRequiredHotelStays(itinerary: TripPlan): string[] {
  if (!itinerary.end_date || itinerary.days.some((day) => !day.date)) {
    return [];
  }
  const days = [...itinerary.days].sort((left, right) => left.day_number - right.day_number);
  const groups: typeof days[] = [];
  days.forEach((day) => {
    const current = groups[groups.length - 1];
    if (!current || normalizeCity(current[0].city) !== normalizeCity(day.city)) {
      groups.push([day]);
    } else {
      current.push(day);
    }
  });
  return groups.slice(0, 5).flatMap((group, index) => {
    const checkIn = group[0].date;
    const checkOut = groups[index + 1]?.[0].date ?? itinerary.end_date;
    if (!checkIn || !checkOut || checkOut <= checkIn) {
      return [];
    }
    return [`${normalizeCity(group[0].city)}|${checkIn}|${checkOut}`];
  });
}

function normalizeCity(value: string | null | undefined): string {
  return (value ?? "").trim().toLocaleLowerCase("en-US").replace(/\s+/g, " ");
}

function budgetComparison(summary: TripCostSummary): string | null {
  const difference = summary.difference_from_budget_usd;
  if (difference == null) {
    return null;
  }
  if (difference > 0) {
    return `${formatMoney(difference)} over your original target budget`;
  }
  if (difference < 0) {
    return `${formatMoney(Math.abs(difference))} under your original target budget`;
  }
  return "This matches your original target budget.";
}

function formatMoney(amount: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(amount);
}
