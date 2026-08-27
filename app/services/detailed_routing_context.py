import math
from dataclasses import dataclass, replace
from datetime import date, datetime

from app.models import (
    Activity,
    FlightOption,
    HotelOption,
    TravelMode,
    TravelSelections,
    TripPlan,
)
from app.services.routing_enrichment import WALK_DISTANCE_THRESHOLD_KM
from app.services.travel_selection import (
    TravelSelectionError,
    validate_travel_selections,
)


class DetailedRoutingContextError(ValueError):
    """Stored travel facts cannot form a safe detailed-routing context."""


@dataclass(frozen=True)
class RoutingPoint:
    stop_id: str
    name: str
    stop_type: str
    latitude: float | None = None
    longitude: float | None = None

    @property
    def has_coordinates(self) -> bool:
        return self.latitude is not None and self.longitude is not None


@dataclass(frozen=True)
class RoutingActivity:
    activity_id: str
    activity: Activity
    point: RoutingPoint


@dataclass(frozen=True)
class RoutingDayContext:
    day_number: int
    date: date
    city: str
    hotel: HotelOption
    hotel_point: RoutingPoint
    activities: tuple[RoutingActivity, ...]


@dataclass(frozen=True)
class FlightRoutingEndpoint:
    airport_code: str
    local_time: datetime
    point: RoutingPoint


@dataclass(frozen=True)
class DetailedRoutingContext:
    trip_plan: TripPlan
    travel_selections: TravelSelections
    selected_flight: FlightOption
    selected_hotels: tuple[HotelOption, ...]
    arrival: FlightRoutingEndpoint
    departure: FlightRoutingEndpoint | None
    days: tuple[RoutingDayContext, ...]
    travelers: int


@dataclass(frozen=True)
class RequiredRouteLeg:
    leg_id: str
    day_number: int
    origin: RoutingPoint
    destination: RoutingPoint
    requested_mode: TravelMode


def build_detailed_routing_context(
    trip_plan: TripPlan,
    travel_selections: TravelSelections,
) -> DetailedRoutingContext:
    """Resolve IDs against one stored recommendation snapshot without providers."""

    try:
        flight, selected_hotels = validate_travel_selections(
            trip_plan,
            travel_selections,
        )
    except TravelSelectionError as exc:
        raise DetailedRoutingContextError(exc.detail) from exc
    if not flight.slices:
        raise DetailedRoutingContextError("The selected flight has no usable journey data.")

    outbound = flight.slices[0]
    arrival_code = outbound.destination_code
    arrival = FlightRoutingEndpoint(
        airport_code=arrival_code,
        local_time=outbound.arrival_at,
        point=RoutingPoint(
            stop_id="arrival-airport",
            name=f"{arrival_code} Airport",
            stop_type="airport",
        ),
    )
    departure = None
    if len(flight.slices) > 1:
        return_slice = flight.slices[-1]
        departure_code = return_slice.origin_code
        departure = FlightRoutingEndpoint(
            airport_code=departure_code,
            local_time=return_slice.departure_at,
            point=RoutingPoint(
                stop_id="departure-airport",
                name=f"{departure_code} Airport",
                stop_type="airport",
            ),
        )

    ordered_days = sorted(trip_plan.days, key=lambda item: item.day_number)
    if not ordered_days or any(day.date is None for day in ordered_days):
        raise DetailedRoutingContextError(
            "Detailed routing requires exact dates for every itinerary day."
        )
    hotel_by_date = _map_hotels_to_dates(selected_hotels, ordered_days[-1].date)
    days: list[RoutingDayContext] = []
    for day in ordered_days:
        assert day.date is not None
        hotel = hotel_by_date.get(day.date)
        if hotel is None:
            raise DetailedRoutingContextError(
                f"No selected hotel covers itinerary day {day.day_number}."
            )
        hotel_point = RoutingPoint(
            stop_id=f"day-{day.day_number}-hotel",
            name=hotel.name,
            stop_type="hotel",
            latitude=hotel.latitude,
            longitude=hotel.longitude,
        )
        activities = tuple(
            _routing_activity(day.day_number, index, activity)
            for index, activity in enumerate(day.activities, start=1)
            if not (
                departure is not None
                and day.day_number == ordered_days[-1].day_number
                and _is_departure_logistics_placeholder(activity)
            )
        )
        days.append(
            RoutingDayContext(
                day_number=day.day_number,
                date=day.date,
                city=day.city,
                hotel=hotel,
                hotel_point=hotel_point,
                activities=activities,
            )
        )
    return DetailedRoutingContext(
        trip_plan=trip_plan,
        travel_selections=travel_selections,
        selected_flight=flight,
        selected_hotels=tuple(selected_hotels),
        arrival=arrival,
        departure=departure,
        days=tuple(days),
        travelers=trip_plan.travelers,
    )


def with_resolved_point(
    context: DetailedRoutingContext,
    *,
    stop_id: str,
    latitude: float,
    longitude: float,
    name: str | None = None,
) -> DetailedRoutingContext:
    """Return context with one airport or hotel point provider-resolved."""

    def update(point: RoutingPoint) -> RoutingPoint:
        if point.stop_id != stop_id:
            return point
        return replace(
            point,
            name=name or point.name,
            latitude=latitude,
            longitude=longitude,
        )

    arrival = replace(context.arrival, point=update(context.arrival.point))
    departure = (
        replace(context.departure, point=update(context.departure.point))
        if context.departure is not None
        else None
    )
    days = tuple(
        replace(day, hotel_point=update(day.hotel_point)) for day in context.days
    )
    return replace(context, arrival=arrival, departure=departure, days=days)


def collect_required_route_legs(
    context: DetailedRoutingContext,
) -> list[RequiredRouteLeg]:
    """Build useful door-to-door legs without inventing schedule details."""

    legs: list[RequiredRouteLeg] = []
    final_day_number = context.days[-1].day_number
    for day in context.days:
        chain: list[tuple[RoutingPoint, RoutingActivity | None]] = [
            (day.hotel_point, None),
            *((activity.point, activity) for activity in day.activities),
            (day.hotel_point, None),
        ]
        if day.day_number == context.days[0].day_number:
            _append_leg(
                legs,
                day.day_number,
                context.arrival.point,
                day.hotel_point,
                "transit",
            )
        for index in range(len(chain) - 1):
            origin, origin_activity = chain[index]
            destination, _ = chain[index + 1]
            mode = _route_mode(origin, destination, origin_activity)
            _append_leg(legs, day.day_number, origin, destination, mode)
        if day.day_number == final_day_number and context.departure is not None:
            _append_leg(
                legs,
                day.day_number,
                day.hotel_point,
                context.departure.point,
                "transit",
            )
    return legs


def _map_hotels_to_dates(
    hotels: list[HotelOption],
    final_itinerary_date: date | None,
) -> dict[date, HotelOption]:
    mapping: dict[date, HotelOption] = {}
    for hotel in hotels:
        current = hotel.check_in
        while current < hotel.check_out:
            if current in mapping:
                raise DetailedRoutingContextError(
                    "Selected hotel stays overlap and cannot be mapped safely."
                )
            mapping[current] = hotel
            current = date.fromordinal(current.toordinal() + 1)
    if final_itinerary_date is not None and final_itinerary_date not in mapping:
        matching_checkout = [
            hotel for hotel in hotels if hotel.check_out == final_itinerary_date
        ]
        if len(matching_checkout) == 1:
            mapping[final_itinerary_date] = matching_checkout[0]
    return mapping


def _routing_activity(
    day_number: int,
    activity_index: int,
    activity: Activity,
) -> RoutingActivity:
    place = activity.place
    trusted = bool(
        place is not None
        and place.provider == "geoapify"
        and place.resolution_status == "resolved"
        and activity.place_resolution_status == "resolved"
    )
    activity_id = f"day-{day_number}-activity-{activity_index}"
    return RoutingActivity(
        activity_id=activity_id,
        activity=activity,
        point=RoutingPoint(
            stop_id=activity_id,
            name=activity.name,
            stop_type="activity",
            latitude=place.latitude if trusted and place else None,
            longitude=place.longitude if trusted and place else None,
        ),
    )


def _is_departure_logistics_placeholder(activity: Activity) -> bool:
    """Detect model-authored placeholders replaced by deterministic routing."""

    normalized = " ".join(activity.name.strip().casefold().split())
    return any(
        phrase in normalized
        for phrase in (
            "departure logistics",
            "airport transfer",
            "travel to airport",
            "transfer to airport",
            "hotel checkout",
            "hotel check-out",
            "check out and depart",
        )
    )


def _append_leg(
    legs: list[RequiredRouteLeg],
    day_number: int,
    origin: RoutingPoint,
    destination: RoutingPoint,
    mode: TravelMode,
) -> None:
    if origin.stop_id == destination.stop_id or _same_coordinates(origin, destination):
        return
    leg_id = f"day-{day_number}-leg-{len(legs) + 1}"
    legs.append(
        RequiredRouteLeg(
            leg_id=leg_id,
            day_number=day_number,
            origin=origin,
            destination=destination,
            requested_mode=mode,
        )
    )


def _route_mode(
    origin: RoutingPoint,
    destination: RoutingPoint,
    origin_activity: RoutingActivity | None,
) -> TravelMode:
    if origin_activity and origin_activity.activity.travel_mode_to_next:
        return origin_activity.activity.travel_mode_to_next
    if origin.has_coordinates and destination.has_coordinates:
        return (
            "walk"
            if _distance_km(origin, destination) <= WALK_DISTANCE_THRESHOLD_KM
            else "transit"
        )
    return "transit"


def straight_line_distance_km(
    origin: RoutingPoint,
    destination: RoutingPoint,
) -> float | None:
    if not origin.has_coordinates or not destination.has_coordinates:
        return None
    return _distance_km(origin, destination)


def _distance_km(origin: RoutingPoint, destination: RoutingPoint) -> float:
    assert origin.latitude is not None and origin.longitude is not None
    assert destination.latitude is not None and destination.longitude is not None
    radius_km = 6371.0088
    lat1 = math.radians(origin.latitude)
    lat2 = math.radians(destination.latitude)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(destination.longitude - origin.longitude)
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return radius_km * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _same_coordinates(origin: RoutingPoint, destination: RoutingPoint) -> bool:
    distance = straight_line_distance_km(origin, destination)
    return distance is not None and distance <= 0.01
