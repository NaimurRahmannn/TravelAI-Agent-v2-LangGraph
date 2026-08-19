from datetime import date

MAX_TRIP_DURATION_DAYS = 365


def validate_and_derive_duration(
    start_date: date,
    end_date: date,
    *,
    today: date | None = None,
) -> int:
    """Validate an inclusive trip range and return its duration in days."""

    current_date = today or date.today()
    if start_date < current_date:
        raise ValueError("Start date cannot be in the past")
    if end_date < start_date:
        raise ValueError("End date cannot be before start date")

    duration = (end_date - start_date).days + 1
    if duration > MAX_TRIP_DURATION_DAYS:
        raise ValueError(
            f"Trip duration cannot exceed {MAX_TRIP_DURATION_DAYS} days"
        )
    return duration
