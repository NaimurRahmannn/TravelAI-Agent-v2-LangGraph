from datetime import UTC, datetime, time, timedelta

from app.models import (
    DetailedRouteLeg,
    DetailedRoutingDay,
    DetailedRoutingPlan,
    TimetableStop,
)
from app.services.detailed_routing_context import (
    DetailedRoutingContext,
    RoutingActivity,
    RoutingDayContext,
)
from app.services.detailed_routing_estimates import PlanningEstimateBundle

INTERNATIONAL_ARRIVAL_PROCESSING_MINUTES = 90
AIRPORT_PREDEPARTURE_BUFFER_MINUTES = 180
AIRLINE_CHECK_IN_MINUTES = 60
SECURITY_AND_IMMIGRATION_MINUTES = 60
GATE_AND_BOARDING_MINUTES = 60
HOTEL_ARRIVAL_BUFFER_MINUTES = 20
HOTEL_DEPARTURE_BUFFER_MINUTES = 15
DEFAULT_DAY_START_TIME = time(9, 0)
UNAVAILABLE_ROUTE_WARNING = "Routing information was unavailable for this stop."
FINAL_ACTIVITY_WARNING = (
    "This activity was removed because it cannot fit safely before the "
    "hotel-to-airport journey and airport processing window."
)
INSUFFICIENT_AIRPORT_BUFFER_WARNING = (
    "The estimated airport arrival leaves less than the recommended three hours "
    "for international check-in, security, immigration, and boarding."
)


def build_detailed_timetable(
    context: DetailedRoutingContext,
    estimates: PlanningEstimateBundle,
    *,
    generated_at: datetime | None = None,
) -> DetailedRoutingPlan:
    """Build all clock times deterministically without invoking providers or LLMs."""

    days: list[DetailedRoutingDay] = []
    plan_warnings: list[str] = []
    for index, day in enumerate(context.days):
        built = _build_day(
            context,
            day,
            estimates,
            is_first=index == 0,
            is_final=index == len(context.days) - 1,
        )
        days.append(built)
        plan_warnings.extend(
            warning for warning in built.warnings if warning not in plan_warnings
        )
    return DetailedRoutingPlan(
        days=days,
        generated_at=generated_at or datetime.now(UTC),
        has_ai_estimates=any(
            leg.duration.source == "llm_estimate"
            for day in days
            for leg in day.route_legs
        )
        or any(
            stop.source == "llm_estimate"
            for day in days
            for stop in day.stops
        ),
        warnings=plan_warnings,
    )


def _build_day(
    context: DetailedRoutingContext,
    day: RoutingDayContext,
    estimates: PlanningEstimateBundle,
    *,
    is_first: bool,
    is_final: bool,
) -> DetailedRoutingDay:
    stops: list[TimetableStop] = []
    used_legs: list[DetailedRouteLeg] = []
    warnings: list[str] = []
    route_lookup = {
        (leg.origin_stop_id, leg.destination_stop_id): leg
        for leg in estimates.route_legs.values()
        if leg.leg_id.startswith(f"day-{day.day_number}-")
    }
    timezone = _day_timezone(context, is_final=is_final)
    current_time = datetime.combine(day.date, DEFAULT_DAY_START_TIME, timezone)
    current_point = day.hotel_point

    if is_first and context.arrival.local_time.date() == day.date:
        current_time = context.arrival.local_time
        stops.append(
            TimetableStop(
                stop_id="arrival-flight",
                name=f"Selected flight arrives at {context.arrival.point.name}",
                stop_type="airport",
                arrival_time=current_time,
                departure_time=current_time,
                source="selected_flight",
            )
        )
        buffer_end = current_time + timedelta(
            minutes=INTERNATIONAL_ARRIVAL_PROCESSING_MINUTES
        )
        stops.append(
            _buffer_stop(
                "arrival-processing",
                "Airport processing: immigration, baggage, and exit",
                current_time,
                buffer_end,
            )
        )
        current_time = buffer_end
        current_time = _append_route(
            route_lookup.get((context.arrival.point.stop_id, day.hotel_point.stop_id)),
            current_time,
            used_legs,
            warnings,
        )
        hotel_buffer_end = current_time + timedelta(
            minutes=HOTEL_ARRIVAL_BUFFER_MINUTES
        )
        stops.append(
            _buffer_stop(
                f"day-{day.day_number}-hotel-arrival-buffer",
                f"Check in or leave luggage at {day.hotel.name}",
                current_time,
                hotel_buffer_end,
            )
        )
        current_time = hotel_buffer_end
    else:
        stops.append(
            TimetableStop(
                stop_id=f"day-{day.day_number}-hotel-start",
                name=f"Start at {day.hotel.name}",
                stop_type="hotel",
                arrival_time=current_time,
                departure_time=current_time,
                source="selected_hotel",
            )
        )

    final_route = None
    latest_hotel_departure = None
    if is_final and context.departure is not None:
        final_route = route_lookup.get(
            (day.hotel_point.stop_id, context.departure.point.stop_id)
        )
        target_airport_arrival = context.departure.local_time - timedelta(
            minutes=AIRPORT_PREDEPARTURE_BUFFER_MINUTES
        )
        route_minutes = _planning_minutes(final_route)
        if route_minutes is not None:
            latest_hotel_departure = target_airport_arrival - timedelta(
                minutes=route_minutes
            )
        else:
            _add_warning(warnings, UNAVAILABLE_ROUTE_WARNING)

    if latest_hotel_departure is not None and not (
        is_first and context.arrival.local_time.date() == day.date
    ):
        departure_preparation_start = latest_hotel_departure - timedelta(
            minutes=HOTEL_DEPARTURE_BUFFER_MINUTES
        )
        if departure_preparation_start < current_time:
            current_time = departure_preparation_start
            if stops and stops[-1].stop_type == "hotel":
                stops[-1] = stops[-1].model_copy(
                    update={
                        "arrival_time": current_time,
                        "departure_time": current_time,
                    }
                )

    for activity in day.activities:
        incoming = route_lookup.get(
            (current_point.stop_id, activity.point.stop_id)
        )
        visit = estimates.visit_durations[activity.activity_id]
        requested_start = _activity_start(day, activity, timezone)
        incoming_minutes = _planning_minutes(incoming) or 0
        route_start = current_time
        if requested_start is not None:
            latest_route_start = requested_start - timedelta(minutes=incoming_minutes)
            if latest_route_start > route_start:
                route_start = latest_route_start
        if latest_hotel_departure is not None:
            return_route = route_lookup.get(
                (activity.point.stop_id, day.hotel_point.stop_id)
            )
            projected = route_start + timedelta(
                minutes=incoming_minutes
                + visit.planning_minutes
                + (_planning_minutes(return_route) or 0)
                + HOTEL_DEPARTURE_BUFFER_MINUTES
            )
            if projected > latest_hotel_departure:
                stops.append(
                    TimetableStop(
                        stop_id=activity.activity_id,
                        name=activity.activity.name,
                        stop_type="activity",
                        planned_visit_minutes=visit.planning_minutes,
                        visit_duration_min_minutes=visit.minimum_minutes,
                        visit_duration_max_minutes=visit.maximum_minutes,
                        source=_visit_source(visit.source),
                        scheduled=False,
                        note=(
                            "Skipped to preserve hotel-to-airport travel plus "
                            "check-in, security, immigration, and boarding time."
                        ),
                    )
                )
                _add_warning(warnings, FINAL_ACTIVITY_WARNING)
                continue

        if route_start > current_time:
            current_time = route_start
            if stops and stops[-1].stop_type == "hotel":
                stops[-1] = stops[-1].model_copy(
                    update={"departure_time": current_time}
                )
        current_time = _append_route(
            incoming,
            current_time,
            used_legs,
            warnings,
        )
        departure = current_time + timedelta(minutes=visit.planning_minutes)
        stops.append(
            TimetableStop(
                stop_id=activity.activity_id,
                name=activity.activity.name,
                stop_type="activity",
                arrival_time=current_time,
                departure_time=departure,
                planned_visit_minutes=visit.planning_minutes,
                visit_duration_min_minutes=visit.minimum_minutes,
                visit_duration_max_minutes=visit.maximum_minutes,
                source=_visit_source(visit.source),
                note=visit.reason,
            )
        )
        current_time = departure
        current_point = activity.point

    if current_point.stop_id != day.hotel_point.stop_id:
        current_time = _append_route(
            route_lookup.get((current_point.stop_id, day.hotel_point.stop_id)),
            current_time,
            used_legs,
            warnings,
        )
        stops.append(
            TimetableStop(
                stop_id=f"day-{day.day_number}-hotel-return",
                name=f"Return to {day.hotel.name}",
                stop_type="hotel",
                arrival_time=current_time,
                departure_time=current_time,
                source="selected_hotel",
            )
        )

    if is_final and context.departure is not None:
        if latest_hotel_departure is not None and current_time <= latest_hotel_departure:
            hotel_buffer_start = latest_hotel_departure - timedelta(
                minutes=HOTEL_DEPARTURE_BUFFER_MINUTES
            )
            if current_time < hotel_buffer_start:
                current_time = hotel_buffer_start
                if stops and stops[-1].stop_type == "hotel":
                    stops[-1] = stops[-1].model_copy(
                        update={"departure_time": current_time}
                    )
            stops.append(
                _buffer_stop(
                    "hotel-departure-buffer",
                    f"Collect luggage and depart {day.hotel.name}",
                    current_time,
                    latest_hotel_departure,
                )
            )
            current_time = latest_hotel_departure
        elif latest_hotel_departure is not None and current_time > latest_hotel_departure:
            _add_warning(
                warnings,
                "The selected return flight cannot retain the full recommended "
                "airport-processing window from the current schedule.",
            )
        current_time = _append_route(
            final_route,
            current_time,
            used_legs,
            warnings,
        )
        airport_arrival = current_time
        stops.append(
            TimetableStop(
                stop_id="departure-airport-arrival",
                name=f"Estimated arrival at {context.departure.point.name}",
                stop_type="airport",
                arrival_time=airport_arrival,
                departure_time=airport_arrival,
                source="planning_policy",
            )
        )
        _append_airport_processing_stops(
            stops,
            airport_arrival=airport_arrival,
            flight_departure=context.departure.local_time,
            warnings=warnings,
        )
        stops.append(
            TimetableStop(
                stop_id="departure-flight",
                name=(
                    f"Selected return flight departs "
                    f"{context.departure.point.name}"
                ),
                stop_type="airport",
                arrival_time=context.departure.local_time,
                departure_time=context.departure.local_time,
                source="selected_flight",
            )
        )
    return DetailedRoutingDay(
        day_number=day.day_number,
        date=day.date,
        city=day.city,
        hotel_name=day.hotel.name,
        stops=stops,
        route_legs=used_legs,
        latest_departure_for_airport=latest_hotel_departure,
        warnings=warnings,
    )


def _append_route(
    leg: DetailedRouteLeg | None,
    departure: datetime,
    used_legs: list[DetailedRouteLeg],
    warnings: list[str],
) -> datetime:
    if leg is None:
        _add_warning(warnings, UNAVAILABLE_ROUTE_WARNING)
        return departure
    minutes = leg.duration.planning_minutes
    if minutes is None:
        used_legs.append(leg.model_copy(update={"departure_time": departure}))
        _add_warning(warnings, UNAVAILABLE_ROUTE_WARNING)
        return departure
    arrival = departure + timedelta(minutes=minutes)
    used_legs.append(
        leg.model_copy(
            update={"departure_time": departure, "arrival_time": arrival}
        )
    )
    return arrival


def _planning_minutes(leg: DetailedRouteLeg | None) -> int | None:
    return leg.duration.planning_minutes if leg is not None else None


def _buffer_stop(
    stop_id: str,
    name: str,
    arrival: datetime,
    departure: datetime,
) -> TimetableStop:
    return TimetableStop(
        stop_id=stop_id,
        name=name,
        stop_type="planning_buffer",
        arrival_time=arrival,
        departure_time=departure,
        source="planning_policy",
        note="Planning buffer",
    )


def _activity_start(
    day: RoutingDayContext,
    activity: RoutingActivity,
    timezone: object,
) -> datetime | None:
    value = activity.activity.start_time
    if not value:
        return None
    normalized = value.strip().upper()
    for pattern in ("%H:%M", "%I:%M %p", "%I %p"):
        try:
            parsed = datetime.strptime(normalized, pattern).time()
            return datetime.combine(day.date, parsed, timezone)
        except ValueError:
            continue
    return None


def _append_airport_processing_stops(
    stops: list[TimetableStop],
    *,
    airport_arrival: datetime,
    flight_departure: datetime,
    warnings: list[str],
) -> None:
    """Reserve explicit international-departure procedures before the flight."""

    if airport_arrival >= flight_departure:
        _add_warning(
            warnings,
            "The estimated airport arrival is not before the selected return flight.",
        )
        return
    recommended_start = flight_departure - timedelta(
        minutes=AIRPORT_PREDEPARTURE_BUFFER_MINUTES
    )
    if airport_arrival > recommended_start:
        stops.append(
            _buffer_stop(
                "reduced-airport-processing-window",
                "Reduced airport processing window",
                airport_arrival,
                flight_departure,
            )
        )
        _add_warning(warnings, INSUFFICIENT_AIRPORT_BUFFER_WARNING)
        return
    current_time = airport_arrival
    if current_time < recommended_start:
        stops.append(
            _buffer_stop(
                "airport-contingency-buffer",
                "Airport arrival contingency buffer",
                current_time,
                recommended_start,
            )
        )
        current_time = recommended_start
    for stop_id, name, minutes in (
        (
            "airport-check-in",
            "Airline check-in and bag drop",
            AIRLINE_CHECK_IN_MINUTES,
        ),
        (
            "airport-security-immigration",
            "Security screening and outbound immigration",
            SECURITY_AND_IMMIGRATION_MINUTES,
        ),
        (
            "airport-gate-boarding",
            "Walk to gate and boarding buffer",
            GATE_AND_BOARDING_MINUTES,
        ),
    ):
        end_time = current_time + timedelta(minutes=minutes)
        stops.append(_buffer_stop(stop_id, name, current_time, end_time))
        current_time = end_time


def _day_timezone(context: DetailedRoutingContext, *, is_final: bool):
    if is_final and context.departure is not None:
        return context.departure.local_time.tzinfo
    return context.arrival.local_time.tzinfo


def _visit_source(source: str):
    if source == "llm_estimate":
        return "llm_estimate"
    if source == "itinerary":
        return "itinerary"
    return "planning_policy"


def _add_warning(warnings: list[str], warning: str) -> None:
    if warning not in warnings:
        warnings.append(warning)
