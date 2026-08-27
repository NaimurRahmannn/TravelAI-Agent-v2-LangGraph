import {
  Bot,
  Clock3,
  MapPinned,
  Route,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import type {
  DetailedRouteLeg,
  DetailedRoutingDay,
  DetailedRoutingPlan,
  TimetableStop,
} from "@/lib/api";

type TimelineEvent =
  | { kind: "stop"; sortTime: string; stop: TimetableStop }
  | { kind: "route"; sortTime: string; leg: DetailedRouteLeg };

const HIDDEN_ROUTING_WARNINGS = new Set([
  "Transit routing was unavailable from Geoapify, so an AI planning estimate is shown for this leg.",
  "The selected flight has no stored return slice, so no airport deadline could be calculated.",
  "Planned activities extend beyond the preferred day-end time.",
]);

export function DetailedRoutingTimeline({
  plan,
}: {
  plan: DetailedRoutingPlan;
}) {
  return (
    <section
      aria-labelledby="detailed-routing-heading"
      className="detailedRoutingPlan"
    >
      <header className="detailedRoutingHeader">
        <div className="detailedRoutingIcon">
          <Route aria-hidden="true" size={22} />
        </div>
        <div>
          <p className="selectionEyebrow">Door-to-door planning view</p>
          <h2 id="detailed-routing-heading">Detailed Routing &amp; Timetable</h2>
          <p>
            Selected travel facts, route estimates, and conservative planning
            buffers combined into a practical daily clock.
          </p>
        </div>
      </header>

      {plan.has_ai_estimates ? (
        <p className="routingEstimateNotice">
          <Bot aria-hidden="true" size={17} />
          AI ranges are planning estimates, not live transit schedules.
        </p>
      ) : null}

      <div className="detailedRoutingDays">
        {plan.days.map((day) => (
          <DetailedRoutingDayCard day={day} key={day.day_number} />
        ))}
      </div>
    </section>
  );
}

function DetailedRoutingDayCard({ day }: { day: DetailedRoutingDay }) {
  const events = buildTimelineEvents(day);
  const omittedActivities = day.stops.filter(
    (stop) => stop.stop_type === "activity" && !stop.scheduled,
  );
  const visibleWarnings = day.warnings.filter(
    (warning) => !HIDDEN_ROUTING_WARNINGS.has(warning),
  );
  return (
    <article className="detailedRoutingDay">
      <header>
        <div>
          <span>Day {day.day_number}</span>
          <h3>{day.city || "Trip day"}</h3>
        </div>
        <time dateTime={day.date}>{formatDate(day.date)}</time>
      </header>
      {day.hotel_name ? (
        <p className="routingHotelBase">
          <MapPinned aria-hidden="true" size={15} />
          Day base: {day.hotel_name}
        </p>
      ) : null}
      {day.latest_departure_for_airport ? (
        <div className="airportDeadline">
          <Clock3 aria-hidden="true" size={17} />
          <div>
            <span>Latest recommended hotel departure for airport</span>
            <strong>{wallClock(day.latest_departure_for_airport)}</strong>
          </div>
        </div>
      ) : null}

      <ol className="routingTimeline">
        {events.map((event) => (
          <li key={`${event.kind}-${event.kind === "stop" ? event.stop.stop_id : event.leg.leg_id}`}>
            {event.kind === "stop" ? (
              <StopEvent stop={event.stop} />
            ) : (
              <RouteEvent leg={event.leg} />
            )}
          </li>
        ))}
      </ol>

      {omittedActivities.length > 0 ? (
        <div className="routingWarnings" role="status">
          <p>
            <TriangleAlert aria-hidden="true" size={15} />
            Removed to protect your return flight: {omittedActivities
              .map((stop) => stop.name)
              .join(", ")}.
          </p>
        </div>
      ) : null}

      {visibleWarnings.length > 0 ? (
        <div className="routingWarnings" role="status">
          {visibleWarnings.map((warning) => (
            <p key={warning}>
              <TriangleAlert aria-hidden="true" size={15} />
              {warning}
            </p>
          ))}
        </div>
      ) : null}
    </article>
  );
}

function StopEvent({ stop }: { stop: TimetableStop }) {
  const source = stopSource(stop);
  return (
    <div className={`timelineEvent stopEvent ${!stop.scheduled ? "unscheduled" : ""}`}>
      <TimelineTime start={stop.arrival_time} end={stop.departure_time} />
      <div className="timelineEventBody">
        <h4>{stop.name}</h4>
        {stop.stop_type === "activity" && stop.scheduled ? (
          <p>
            Suggested visit: {visitRange(stop)} · Timetable allocation: {" "}
            {formatMinutes(stop.planned_visit_minutes)}
          </p>
        ) : null}
        {stop.note && stop.stop_type !== "planning_buffer" ? (
          <p>{stop.note}</p>
        ) : null}
        <SourceLabel source={source} />
      </div>
    </div>
  );
}

function RouteEvent({ leg }: { leg: DetailedRouteLeg }) {
  const source = routeSource(leg);
  return (
    <div className="timelineEvent routeEvent">
      <TimelineTime start={leg.departure_time} end={leg.arrival_time} />
      <div className="timelineEventBody">
        <h4>
          {leg.origin_name} <span aria-hidden="true">→</span>{" "}
          {leg.destination_name}
        </h4>
        <p>
          {formatMode(leg.resolved_mode || leg.requested_mode)} · {routeDuration(leg)}
          {leg.distance_km != null ? ` · ${leg.distance_km.toFixed(1)} km` : ""}
        </p>
        <SourceLabel source={source} />
      </div>
    </div>
  );
}

function TimelineTime({
  start,
  end,
}: {
  start?: string | null;
  end?: string | null;
}) {
  if (!start) {
    return <span className="timelineTime">Not scheduled</span>;
  }
  return (
    <time className="timelineTime" dateTime={start}>
      {wallClock(start)}
      {end && end !== start ? `–${wallClock(end)}` : ""}
    </time>
  );
}

function SourceLabel({ source }: { source: string }) {
  const Icon = source === "Planning buffer" ? ShieldCheck : source.startsWith("AI") ? Bot : Route;
  return (
    <span className="routeSourceLabel">
      <Icon aria-hidden="true" size={13} />
      {source}
    </span>
  );
}

function buildTimelineEvents(day: DetailedRoutingDay): TimelineEvent[] {
  const events: TimelineEvent[] = [
    ...day.stops.filter((stop) => stop.scheduled).map(
      (stop): TimelineEvent => ({
        kind: "stop",
        sortTime: stop.arrival_time || "9999",
        stop,
      }),
    ),
    ...day.route_legs.map(
      (leg): TimelineEvent => ({
        kind: "route",
        sortTime: leg.departure_time || "9999",
        leg,
      }),
    ),
  ];
  return events.sort((left, right) => left.sortTime.localeCompare(right.sortTime));
}

function routeSource(leg: DetailedRouteLeg): string {
  if (leg.duration.source === "geoapify") return "Geoapify route estimate";
  if (leg.duration.source === "llm_estimate") return "AI planning estimate";
  if (leg.duration.source === "planning_policy") return "Planning buffer";
  return "Routing unavailable";
}

function stopSource(stop: TimetableStop): string {
  if (!stop.scheduled) return "Not scheduled";
  if (stop.source === "llm_estimate") return "AI visit estimate";
  if (stop.source === "planning_policy") return "Planning buffer";
  if (stop.source === "selected_flight") return "Selected flight fact";
  if (stop.source === "selected_hotel") return "Selected hotel";
  return "Existing itinerary time";
}

function routeDuration(leg: DetailedRouteLeg): string {
  const duration = leg.duration;
  if (duration.source === "llm_estimate") {
    return `~${duration.min_minutes}–${duration.max_minutes} min`;
  }
  if (duration.planning_minutes != null) {
    return formatMinutes(duration.planning_minutes);
  }
  return "Duration unavailable";
}

function visitRange(stop: TimetableStop): string {
  if (stop.visit_duration_min_minutes == null) return "Unavailable";
  if (stop.visit_duration_min_minutes === stop.visit_duration_max_minutes) {
    return formatMinutes(stop.visit_duration_min_minutes);
  }
  return `${stop.visit_duration_min_minutes}–${stop.visit_duration_max_minutes} min`;
}

function formatMinutes(value?: number | null): string {
  if (value == null) return "Unavailable";
  if (value < 60) return `${value} min`;
  const hours = Math.floor(value / 60);
  const minutes = value % 60;
  return minutes ? `${hours}h ${minutes}m` : `${hours}h`;
}

function formatMode(value: string): string {
  return value === "transit"
    ? "Public transit"
    : value.charAt(0).toUpperCase() + value.slice(1);
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "long",
    day: "numeric",
  }).format(new Date(`${value}T00:00:00`));
}

function wallClock(value: string): string {
  const match = value.match(/T(\d{2}):(\d{2})/);
  if (!match) return value;
  const hour = Number(match[1]);
  const minute = match[2];
  const suffix = hour >= 12 ? "PM" : "AM";
  const displayHour = hour % 12 || 12;
  return `${displayHour}:${minute} ${suffix}`;
}
