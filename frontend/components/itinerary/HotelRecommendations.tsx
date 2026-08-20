import { useState } from "react";
import { Building2, CircleAlert } from "lucide-react";
import type {
  HotelOption,
  RecommendationStatus,
  TripPlan,
} from "@/lib/api";

type HotelRecommendationsProps = {
  idPrefix: string;
  itinerary: TripPlan;
};

type HotelGroup = {
  city: string;
  checkIn: string;
  checkOut: string;
  nights: number;
  hotels: HotelOption[];
};

export function HotelRecommendations({
  idPrefix,
  itinerary,
}: HotelRecommendationsProps) {
  const recommendations = itinerary.recommendations;
  if (
    !recommendations ||
    recommendations.hotel_status.status === "not_searched"
  ) {
    return null;
  }

  const headingId = `${idPrefix}-hotels-heading`;
  const groups = groupHotels(recommendations.hotels);

  return (
    <section aria-labelledby={headingId} className="hotelRecommendations">
      <header className="hotelSectionHeader">
        <span>
          <Building2 aria-hidden="true" size={20} />
        </span>
        <div>
          <p>Current hotel search</p>
          <h3 id={headingId}>Hotel recommendations</h3>
        </div>
      </header>

      {groups.length > 0 ? (
        <div className="hotelStayGroups">
          {groups.map((group) => (
            <section
              className="hotelStayGroup"
              key={`${group.city}-${group.checkIn}-${group.checkOut}`}
            >
              <header>
                <h4>Hotels in {group.city}</h4>
                <p>
                  {formatDateRange(group.checkIn, group.checkOut)} · {group.nights}{" "}
                  {group.nights === 1 ? "night" : "nights"}
                </p>
              </header>
              <div className="hotelCardGrid">
                {group.hotels.map((hotel) => (
                  <HotelCard hotel={hotel} key={hotel.provider_offer_id} />
                ))}
              </div>
            </section>
          ))}
        </div>
      ) : (
        <HotelEmptyState status={recommendations.hotel_status.status} />
      )}

      <div className="hotelDisclaimer">
        <p>
          Current hotel-search rates. Prices and availability can change before
          booking.
        </p>
        <p>Hotel search data from LiteAPI / Nuitee Connect.</p>
      </div>
    </section>
  );
}

function HotelCard({ hotel }: { hotel: HotelOption }) {
  const [imageFailed, setImageFailed] = useState(false);

  return (
    <article className="hotelCard">
      {hotel.image_url && !imageFailed ? (
        <div className="hotelImageFrame">
          <img
            alt={`${hotel.name} exterior`}
            className="hotelImage"
            loading="lazy"
            onError={() => setImageFailed(true)}
            src={hotel.image_url}
          />
        </div>
      ) : null}
      <header>
        <div>
          <span className="hotelRecommendationTag">Hotel recommendation</span>
          {hotel.is_sandbox ? (
            <span className="hotelSandboxTag">Sandbox hotel data</span>
          ) : null}
        </div>
        <h5>{hotel.name}</h5>
        <p>{hotel.formatted_address || hotel.city || "Location unavailable"}</p>
      </header>

      <div className="hotelFacts">
        {hotel.room_name ? <span>{hotel.room_name}</span> : null}
        {hotel.board_name ? <span>{hotel.board_name}</span> : null}
        {hotel.rating != null ? <span>Rating {hotel.rating}</span> : null}
        {hotel.refundable != null ? (
          <span>{hotel.refundable ? "Refundable" : "Non-refundable"}</span>
        ) : null}
        {hotel.taxes_included != null ? (
          <span>
            {hotel.taxes_included ? "Taxes included" : "Taxes not included"}
          </span>
        ) : null}
      </div>

      <footer className="hotelPricePanel">
        <div>
          <span>Total stay</span>
          <strong>{formatMoney(hotel.total_price, hotel.currency)}</strong>
        </div>
        {hotel.price_per_night != null ? (
          <p>{formatMoney(hotel.price_per_night, hotel.currency)}/night</p>
        ) : null}
      </footer>
    </article>
  );
}

function HotelEmptyState({ status }: { status: RecommendationStatus }) {
  const copy: Record<RecommendationStatus, string> = {
    not_searched: "Hotel search was not requested.",
    available: "Hotel recommendations are available.",
    no_results: "No matching hotel rates were found for these stays.",
    unavailable: "Hotel search is temporarily unavailable.",
  };
  return (
    <div className="hotelEmptyState">
      <CircleAlert aria-hidden="true" size={19} />
      <p>{copy[status]}</p>
    </div>
  );
}

function groupHotels(hotels: HotelOption[]): HotelGroup[] {
  const groups = new Map<string, HotelGroup>();
  hotels.forEach((hotel) => {
    const city = hotel.city || "this stay";
    const key = `${city}\u0000${hotel.check_in}\u0000${hotel.check_out}`;
    const existing = groups.get(key);
    if (existing) {
      existing.hotels.push(hotel);
      return;
    }
    groups.set(key, {
      city,
      checkIn: hotel.check_in,
      checkOut: hotel.check_out,
      nights: hotel.nights,
      hotels: [hotel],
    });
  });
  return Array.from(groups.values());
}

function formatDateRange(checkIn: string, checkOut: string): string {
  return `${formatDate(checkIn)} – ${formatDate(checkOut)}`;
}

function formatDate(value: string): string {
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
  }).format(date);
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
