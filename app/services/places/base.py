from dataclasses import dataclass
from typing import Literal, Protocol
import re
import unicodedata

from app.models import ResolvedPlace


ResolutionStatus = Literal["resolved", "partially_resolved", "unresolved"]


@dataclass(frozen=True)
class PlaceResolution:
    """Internal provider result, including normal unresolved outcomes."""

    status: ResolutionStatus
    place: ResolvedPlace | None = None

    def __post_init__(self) -> None:
        if self.place is None and self.status != "unresolved":
            raise ValueError("Resolved statuses require place data")
        if self.place is not None and self.place.resolution_status != self.status:
            raise ValueError("Resolution and place statuses must match")

    @classmethod
    def unresolved(cls) -> "PlaceResolution":
        return cls(status="unresolved")


class PlacesProvider(Protocol):
    """Minimal provider boundary used by itinerary enrichment."""

    async def resolve_place(
        self,
        *,
        name: str,
        location_hint: str | None,
        city: str | None,
        destination: str,
    ) -> PlaceResolution:
        ...


def normalize_place_text(value: str | None) -> str:
    """Normalize place text for deterministic comparison and cache keys."""

    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    without_marks = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return " ".join(re.findall(r"[a-z0-9]+", without_marks))


def build_place_query(
    *,
    name: str,
    location_hint: str | None,
    city: str | None,
    destination: str,
) -> str:
    """Build a concise place query without repeated location components."""

    candidates = [name]
    if location_hint and location_hint.strip():
        candidates.extend(location_hint.split(","))
    candidates.extend([city or "", destination])

    parts: list[str] = []
    normalized_parts: list[str] = []
    for candidate in candidates:
        clean = " ".join(candidate.strip().split())
        normalized = normalize_place_text(clean)
        if not normalized:
            continue
        if any(
            normalized == existing
            or normalized in existing
            or existing in normalized
            for existing in normalized_parts
        ):
            continue
        parts.append(clean)
        normalized_parts.append(normalized)

    if not parts:
        raise ValueError("Place query requires at least one non-empty component")
    return ", ".join(parts)
