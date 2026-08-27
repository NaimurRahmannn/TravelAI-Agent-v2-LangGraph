from datetime import datetime

from app.models import (
    DetailedRouteLeg,
    DetailedRoutingPlan,
    TimetableStop,
    TravelSelections,
    TripCostSummary,
    TripPlan,
)
from app.models.recommendations import FlightSearchScope
from app.services.selection_status import build_travel_selection_status

_HIDDEN_ROUTING_WARNINGS = frozenset(
    {
        (
            "Transit routing was unavailable from Geoapify, so an AI planning "
            "estimate is shown for this leg."
        ),
        (
            "The selected flight has no stored return slice, so no airport "
            "deadline could be calculated."
        ),
        "Planned activities extend beyond the preferred day-end time.",
    }
)


def render_itinerary(
    plan: TripPlan,
    *,
    travel_selections: TravelSelections | None = None,
    trip_cost_summary: TripCostSummary | None = None,
    detailed_routing_plan: DetailedRoutingPlan | None = None,
) -> str:
    """Render a structured trip plan as stable Markdown without an LLM."""

    lines = [f"# {plan.title}"]
    if plan.summary:
        lines.extend(["", plan.summary])

    if plan.recommendations and plan.recommendations.flights:
        lines.extend(["", "## Flight Recommendations", ""])
        for option in plan.recommendations.flights:
            airline = " + ".join(option.airline_names) or "Airline unavailable"
            lines.append(f"- **Flight recommendation: {airline}**")
            for index, flight_slice in enumerate(option.slices):
                if len(option.slices) == 2:
                    label = "Outbound" if index == 0 else "Return"
                else:
                    label = f"Leg {index + 1}"
                lines.append(
                    f"  - {label}: {flight_slice.origin_code} → "
                    f"{flight_slice.destination_code} on "
                    f"{flight_slice.departure_at.date()} "
                    f"({_format_stops(flight_slice.stops)}, "
                    f"{_format_duration(flight_slice.duration_minutes)})"
                )
            lines.append(
                f"  - Total for {option.adults} adult"
                f"{'s' if option.adults != 1 else ''}: "
                f"{_format_money(option.total_price, option.currency)}"
            )
        lines.extend(
            [
                "",
                "Current flight-search prices from Google Flights via Swoop. "
                "Prices and availability can change before booking.",
            ]
        )

    if plan.recommendations and plan.recommendations.hotels:
        lines.extend(["", "## Hotel Recommendations", ""])
        current_stay: tuple[str, object, object] | None = None
        for option in plan.recommendations.hotels:
            stay = (option.city or "This stay", option.check_in, option.check_out)
            if stay != current_stay:
                lines.extend(
                    [
                        f"### Hotels in {stay[0]}",
                        "",
                        f"{option.check_in} to {option.check_out} "
                        f"({option.nights} night"
                        f"{'s' if option.nights != 1 else ''})",
                        "",
                    ]
                )
                current_stay = stay
            sandbox = " — Sandbox hotel data" if option.is_sandbox else ""
            lines.append(f"- **Hotel recommendation: {option.name}**{sandbox}")
            if option.formatted_address:
                lines.append(f"  - Address: {option.formatted_address}")
            if option.room_name:
                lines.append(f"  - Room: {option.room_name}")
            if option.board_name:
                lines.append(f"  - Board: {option.board_name}")
            lines.append(
                f"  - Total stay: {_format_money(option.total_price, option.currency)}"
            )
            if option.price_per_night is not None:
                lines.append(
                    f"  - Per night: "
                    f"{_format_money(option.price_per_night, option.currency)}"
                )
            if option.refundable is not None:
                lines.append(
                    "  - " + ("Refundable" if option.refundable else "Non-refundable")
                )
            if option.taxes_included is not None:
                lines.append(
                    "  - "
                    + (
                        "Taxes included"
                        if option.taxes_included
                        else "Taxes not included"
                    )
                )
        lines.extend(
            [
                "",
                "Current hotel-search rates from LiteAPI / Nuitee Connect. "
                "Prices and availability can change before booking.",
            ]
        )

    selection_status = build_travel_selection_status(plan, travel_selections)
    _append_selection_prompt(lines, selection_status.flight, selection_status.hotel)

    for day in plan.days:
        day_heading = f"## Day {day.day_number} — {day.city}"
        if day.date:
            day_heading += f" ({day.date})"
        lines.extend(["", day_heading, ""])

        for index, activity in enumerate(day.activities, start=1):
            lines.append(f"{index}. **{activity.name}**")
            details = []
            if activity.description:
                details.append(activity.description)
            if activity.location_hint:
                details.append(f"Location: {activity.location_hint}")
            if activity.place and activity.place.formatted_address:
                details.append(f"Address: {activity.place.formatted_address}")
            if activity.start_time or activity.end_time:
                details.append(
                    "Time: " + _format_time_range(activity.start_time, activity.end_time)
                )
            if activity.estimated_cost_usd is not None:
                details.append(
                    f"Estimated activity cost: {_format_usd(activity.estimated_cost_usd)}"
                )
            if activity.reason_for_recommendation:
                details.append(activity.reason_for_recommendation)
            for detail in details:
                lines.append(f"   {detail}")
            lines.append("")

        if day.estimated_daily_cost_usd is not None:
            lines.append(
                "**Listed activity costs:** "
                f"{_format_usd(day.estimated_daily_cost_usd)}"
            )

    lines.extend(
        [
            "",
            "## Base Trip Estimate",
            "",
            "Flights and accommodation are not included.",
            "",
        ]
    )
    for item in plan.budget.items:
        budget_line = f"- {item.category}: {_format_usd(item.amount_usd)}"
        if item.note:
            budget_line += f" — {item.note}"
        lines.append(budget_line)

    lines.extend(
        [
            "",
            f"**Base trip estimate:** {_format_usd(plan.budget.estimated_total_usd)}",
        ]
    )
    if plan.budget.user_budget_usd is not None:
        traveler_label = "traveler" if plan.travelers == 1 else "travelers"
        lines.extend(
            [
                "",
                f"**Overall target budget (total for {plan.travelers} {traveler_label}):** "
                f"{_format_usd(plan.budget.user_budget_usd)}",
            ]
        )
    if plan.practical_notes:
        lines.extend(["", "## Practical Notes", ""])
        lines.extend(f"- {note}" for note in plan.practical_notes)

    if travel_selections is not None and trip_cost_summary is not None:
        _append_selected_travel(
            lines,
            plan,
            travel_selections,
            trip_cost_summary,
        )
    if detailed_routing_plan is not None:
        _append_detailed_routing(lines, detailed_routing_plan)

    return "\n".join(lines).strip()


def render_flight_recommendations(
    plan: TripPlan,
    *,
    scope: FlightSearchScope,
) -> str:
    """Render a focused response for an explicit conversational flight search."""

    heading = {
        "outbound": "Departure Flight Suggestions",
        "return": "Return Flight Suggestions",
        "round_trip": "Round-Trip Flight Suggestions",
    }[scope]
    lines = [f"## {heading}"]
    if scope == "round_trip" and plan.start_date and plan.end_date:
        lines.extend(
            [
                "",
                f"Departure: **{plan.start_date}** · Return: **{plan.end_date}**",
            ]
        )
    else:
        date_label = plan.end_date if scope == "return" else plan.start_date
        if date_label is not None:
            lines.extend(["", f"Travel date: **{date_label}**"])

    recommendations = plan.recommendations
    status = (
        recommendations.flight_status.status
        if recommendations is not None
        else "not_searched"
    )
    flights = recommendations.flights if recommendations is not None else []
    if not flights:
        message = {
            "no_results": "No matching flights were found for this date.",
            "unavailable": (
                "Flight search is temporarily unavailable. Please try again shortly."
            ),
            "not_searched": (
                "The current trip does not contain enough information to search flights."
            ),
        }.get(status, "No matching flights were found for this date.")
        lines.extend(["", message])
        return "\n".join(lines)

    for option_number, option in enumerate(flights, start=1):
        airline = " + ".join(option.airline_names) or "Airline unavailable"
        lines.extend(["", f"{option_number}. **{airline}**"])
        for index, flight_slice in enumerate(option.slices):
            if scope == "round_trip" and len(option.slices) == 2:
                label = "Outbound" if index == 0 else "Return"
            elif scope == "return":
                label = "Return"
            else:
                label = "Departure"
            lines.extend(
                [
                    f"   - {label}: {flight_slice.origin_code} → "
                    f"{flight_slice.destination_code}",
                    f"   - Departs: {_format_flight_datetime(flight_slice.departure_at)}",
                    f"   - Arrives: {_format_flight_datetime(flight_slice.arrival_at)}",
                    f"   - {_format_stops(flight_slice.stops)}; "
                    f"{_format_duration(flight_slice.duration_minutes)}",
                ]
            )
        lines.append(
            f"   - Total for {option.adults} adult"
            f"{'s' if option.adults != 1 else ''}: "
            f"{_format_money(option.total_price, option.currency)}"
        )

    lines.extend(
        [
            "",
            "Current flight-search prices from Google Flights via Swoop. "
            "Prices and availability can change before booking.",
        ]
    )
    return "\n".join(lines)


def render_hotel_recommendations(plan: TripPlan) -> str:
    """Render a focused response for an explicit conversational hotel search."""

    lines = ["## Hotel Suggestions"]
    recommendations = plan.recommendations
    status = (
        recommendations.hotel_status.status
        if recommendations is not None
        else "not_searched"
    )
    hotels = recommendations.hotels if recommendations is not None else []
    if not hotels:
        message = {
            "no_results": "No matching hotel rates were found for these dates.",
            "unavailable": (
                "Hotel search is temporarily unavailable. Please try again shortly."
            ),
            "not_searched": (
                "The current trip does not contain enough information to search hotels."
            ),
        }.get(status, "No matching hotel rates were found for these dates.")
        return "\n\n".join([*lines, message])

    current_stay: tuple[str, object, object] | None = None
    for option_number, option in enumerate(hotels, start=1):
        stay = (option.city or "This stay", option.check_in, option.check_out)
        if stay != current_stay:
            lines.extend(
                [
                    "",
                    f"### {stay[0]} · {option.check_in} to {option.check_out}",
                ]
            )
            current_stay = stay
        lines.extend(
            [
                "",
                f"{option_number}. **{option.name}**",
                f"   - {option.nights} night"
                f"{'s' if option.nights != 1 else ''}",
                f"   - Total: {_format_money(option.total_price, option.currency)}",
            ]
        )
        if option.price_per_night is not None:
            lines.append(
                "   - Per night: "
                f"{_format_money(option.price_per_night, option.currency)}"
            )
    lines.extend(
        [
            "",
            "Current hotel-search rates from LiteAPI / Nuitee Connect. "
            "Prices and availability can change before booking.",
        ]
    )
    return "\n".join(lines)


def _format_flight_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M %Z").strip()


def _append_selection_prompt(
    lines: list[str],
    flight_status: str,
    hotel_status: str,
) -> None:
    """Render the deterministic next action after fresh recommendations."""

    if flight_status == "required" and hotel_status == "required":
        lines.extend(
            [
                "",
                "## Select Your Travel Options",
                "",
                "Would you like to select one flight and one hotel for each "
                "stay? No booking will be made.",
            ]
        )


def _append_selected_travel(
    lines: list[str],
    plan: TripPlan,
    selections: TravelSelections,
    summary: TripCostSummary,
) -> None:
    recommendations = plan.recommendations
    if recommendations is None:
        return
    selected_flight = next(
        (
            option
            for option in recommendations.flights
            if option.provider_offer_id == selections.selected_flight_id
        ),
        None,
    )
    selected_hotels = []
    for selection in selections.selected_hotels:
        option = next(
            (
                hotel
                for hotel in recommendations.hotels
                if hotel.provider_offer_id == selection.hotel_option_id
                and hotel.stay_key == selection.stay_key
            ),
            None,
        )
        if option is not None:
            selected_hotels.append(option)
    if selected_flight is None or len(selected_hotels) != len(
        selections.selected_hotels
    ):
        return

    airline = " + ".join(selected_flight.airline_names) or "Airline unavailable"
    route = " / ".join(
        f"{flight_slice.origin_code} → {flight_slice.destination_code}"
        for flight_slice in selected_flight.slices
    )
    lines.extend(
        [
            "",
            "## Selected Travel",
            "",
            f"- **Selected flight: {airline}**",
            f"  - Route: {route}",
            f"  - Total: {_format_usd(summary.selected_flight_usd)}",
        ]
    )
    for hotel in selected_hotels:
        lines.extend(
            [
                f"- **Selected hotel · {hotel.city or 'This stay'}: {hotel.name}**",
                f"  - {hotel.check_in} to {hotel.check_out}",
                f"  - Total stay: {_format_money(hotel.total_price, hotel.currency)}",
            ]
        )

    lines.extend(
        [
            "",
            "## Updated Trip Cost",
            "",
            f"- Base Trip Estimate: {_format_usd(summary.base_trip_total_usd)}",
            f"- Selected Flight: {_format_usd(summary.selected_flight_usd)}",
            f"- Selected Hotels: {_format_usd(summary.selected_hotels_usd)}",
            f"- Travel Additions: {_format_usd(summary.additions_total_usd)}",
            "",
            f"**Updated Trip Total:** {_format_usd(summary.updated_trip_total_usd)}",
        ]
    )
    if summary.difference_from_budget_usd is not None:
        difference = summary.difference_from_budget_usd
        if difference > 0:
            comparison = (
                f"{_format_usd(difference)} is the extra money needed for "
                "flight and hotel"
            )
        elif difference < 0:
            comparison = (
                f"{_format_usd(abs(difference))} under your original target budget"
            )
        else:
            comparison = "Matches your original target budget"
        lines.append(f"- {comparison}")
    lines.extend(
        [
            "",
            "Selected for trip-cost planning only. No reservation or purchase "
            "has been made.",
        ]
    )


def _append_detailed_routing(
    lines: list[str],
    plan: DetailedRoutingPlan,
) -> None:
    lines.extend(["", "## Detailed Routing & Timetable"])
    if plan.has_ai_estimates:
        lines.extend(
            [
                "",
                "AI planning estimates are planning ranges, not a live transit schedule.",
            ]
        )
    for day in plan.days:
        lines.extend(["", f"### Day {day.day_number} — {day.city or 'Trip day'}", ""])
        events: list[tuple[datetime | None, int, str]] = []
        for index, stop in enumerate(day.stops):
            events.append((stop.arrival_time, index * 2, _render_timetable_stop(stop)))
        offset = len(day.stops) * 2
        for index, leg in enumerate(day.route_legs):
            events.append(
                (leg.departure_time, offset + index * 2 + 1, _render_route_leg(leg))
            )
        events.sort(
            key=lambda item: (
                item[0] is None,
                item[0] or datetime.max,
                item[1],
            )
        )
        lines.extend(f"- {event}" for _, _, event in events)
        lines.extend(
            f"- Warning: {warning}"
            for warning in day.warnings
            if warning not in _HIDDEN_ROUTING_WARNINGS
        )
    visible_plan_warnings = [
        warning
        for warning in plan.warnings
        if warning not in _HIDDEN_ROUTING_WARNINGS
    ]
    if visible_plan_warnings:
        lines.extend(["", "Planning warnings:"])
        lines.extend(f"- {warning}" for warning in visible_plan_warnings)


def _render_timetable_stop(stop: TimetableStop) -> str:
    if not stop.scheduled:
        return f"Not scheduled — {stop.name}: {stop.note or 'Timing unavailable'}"
    timing = _format_datetime_range(stop.arrival_time, stop.departure_time)
    source = {
        "planning_policy": "Planning buffer",
        "llm_estimate": "AI planning estimate",
        "selected_flight": "Selected flight fact",
        "selected_hotel": "Selected hotel",
        "itinerary": "Existing itinerary time",
    }[stop.source]
    visit = ""
    if stop.stop_type == "activity" and stop.planned_visit_minutes is not None:
        visit = f" · timetable allocation {stop.planned_visit_minutes} min"
        if (
            stop.visit_duration_min_minutes != stop.visit_duration_max_minutes
            and stop.visit_duration_min_minutes is not None
            and stop.visit_duration_max_minutes is not None
        ):
            visit += (
                f" from {stop.visit_duration_min_minutes}–"
                f"{stop.visit_duration_max_minutes} min range"
            )
    return f"{timing} — {stop.name} · {source}{visit}"


def _render_route_leg(leg: DetailedRouteLeg) -> str:
    timing = _format_datetime_range(leg.departure_time, leg.arrival_time)
    mode = leg.requested_mode.title()
    duration = leg.duration
    if duration.source == "geoapify":
        source = "Geoapify route estimate"
        metrics = f"{duration.planning_minutes} min"
        if leg.distance_km is not None:
            metrics += f" · {leg.distance_km:g} km"
    elif duration.source == "llm_estimate":
        source = "AI planning estimate"
        metrics = f"~{duration.min_minutes}–{duration.max_minutes} min"
    elif duration.source == "planning_policy":
        source = "Planning buffer"
        metrics = f"{duration.planning_minutes} min"
    else:
        source = "Routing unavailable"
        metrics = "duration unavailable"
    return (
        f"{timing} — {leg.origin_name} → {leg.destination_name} · "
        f"{mode} · {metrics} · {source}"
    )


def _format_datetime_range(
    start: datetime | None,
    end: datetime | None,
) -> str:
    if start is None:
        return "Time unavailable"
    start_text = start.strftime("%H:%M")
    if end is None or end == start:
        return start_text
    return f"{start_text}–{end.strftime('%H:%M')}"


def _format_usd(amount: float) -> str:
    """Format a USD estimate consistently, omitting unnecessary cents."""

    if amount.is_integer():
        return f"${amount:,.0f}"
    return f"${amount:,.2f}"


def _format_money(amount: float, currency: str) -> str:
    if currency == "USD":
        return _format_usd(amount)
    formatted = f"{amount:,.0f}" if amount.is_integer() else f"{amount:,.2f}"
    return f"{currency} {formatted}"


def _format_stops(stops: int) -> str:
    if stops == 0:
        return "nonstop"
    return f"{stops} stop" + ("s" if stops != 1 else "")


def _format_duration(minutes: int) -> str:
    hours, remainder = divmod(minutes, 60)
    if hours == 0:
        return f"{remainder}m"
    return f"{hours}h" if remainder == 0 else f"{hours}h {remainder}m"


def _format_time_range(start_time: str | None, end_time: str | None) -> str:
    """Format optional activity start and end times."""

    if start_time and end_time:
        return f"{start_time}–{end_time}"
    return start_time or end_time or ""
