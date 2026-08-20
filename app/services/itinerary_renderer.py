from app.models import TripPlan


def render_itinerary(plan: TripPlan) -> str:
    """Render a structured trip plan as stable Markdown without an LLM."""

    lines = [f"# {plan.title}"]
    if plan.summary:
        lines.extend(["", plan.summary])

    if plan.recommendations and plan.recommendations.flights:
        lines.extend(["", "## Flight Recommendations", ""])
        for option in plan.recommendations.flights:
            airline = option.airline_name or "Flight option"
            lines.append(f"- **{airline}**")
            for index, flight_slice in enumerate(option.slices):
                if len(option.slices) == 2:
                    label = "Outbound" if index == 0 else "Return"
                else:
                    label = f"Leg {index + 1}"
                stop_label = (
                    "nonstop"
                    if flight_slice.stops == 0
                    else f"{flight_slice.stops} stop"
                    + ("s" if flight_slice.stops != 1 else "")
                )
                lines.append(
                    f"  - {label}: {flight_slice.origin_code} → "
                    f"{flight_slice.destination_code} ({stop_label})"
                )
            operating_carriers = sorted(
                {
                    segment.operating_carrier_name
                    for flight_slice in option.slices
                    for segment in flight_slice.segments
                }
            )
            if operating_carriers:
                lines.append(f"  - Operated by: {', '.join(operating_carriers)}")
            lines.append(
                f"  - Total for {plan.travelers} adult"
                f"{'s' if plan.travelers != 1 else ''}: "
                f"{_format_money(option.total_price, option.currency)}"
            )
            evaluation = option.budget_evaluation
            if evaluation and evaluation.projected_trip_total_usd is not None:
                lines.append(
                    "  - Projected trip total: "
                    f"{_format_usd(evaluation.projected_trip_total_usd)}"
                )
            if option.live_data is False:
                lines.append("  - Test flight data")
        lines.extend(
            ["", "Flight prices can change. Optional extras may cost more."]
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

    lines.extend(["", "## Budget Breakdown", ""])
    for item in plan.budget.items:
        budget_line = f"- {item.category}: {_format_usd(item.amount_usd)}"
        if item.note:
            budget_line += f" — {item.note}"
        lines.append(budget_line)

    lines.extend(
        [
            "",
            f"**Estimated total:** {_format_usd(plan.budget.estimated_total_usd)}",
        ]
    )
    if plan.budget.user_budget_usd is not None:
        traveler_label = "traveler" if plan.travelers == 1 else "travelers"
        lines.extend(
            [
                "",
                f"**Traveler budget (total for {plan.travelers} {traveler_label}):** "
                f"{_format_usd(plan.budget.user_budget_usd)}",
            ]
        )
    if plan.budget.international_travel_included is not None:
        travel_scope = (
            "Included"
            if plan.budget.international_travel_included
            else "Not included"
        )
        lines.extend(["", f"**International travel:** {travel_scope}"])
    if plan.budget.within_budget is not None:
        status = "Within budget" if plan.budget.within_budget else "Over budget"
        lines.extend(["", f"**Budget status:** {status}"])

    if plan.practical_notes:
        lines.extend(["", "## Practical Notes", ""])
        lines.extend(f"- {note}" for note in plan.practical_notes)

    return "\n".join(lines).strip()


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


def _format_time_range(start_time: str | None, end_time: str | None) -> str:
    """Format optional activity start and end times."""

    if start_time and end_time:
        return f"{start_time}–{end_time}"
    return start_time or end_time or ""
