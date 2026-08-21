from app.models import TravelSelections, TripCostSummary, TripPlan


def render_itinerary(
    plan: TripPlan,
    *,
    travel_selections: TravelSelections | None = None,
    trip_cost_summary: TripCostSummary | None = None,
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

    return "\n".join(lines).strip()


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
