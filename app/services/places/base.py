import re
import unicodedata
from dataclasses import dataclass
from typing import Literal, Protocol

from app.models import ResolvedPlace

ResolutionStatus = Literal["resolved", "partially_resolved", "unresolved"]

_TRAILING_ACTIVITY_WORDS = frozenset(
    {
        "adventure",
        "experience",
        "exploration",
        "excursion",
        "tour",
        "visit",
        "walk",
    }
)
_LANDMARK_WORDS = frozenset(
    {
        "abbey",
        "basilica",
        "bridge",
        "building",
        "castle",
        "cathedral",
        "church",
        "crossing",
        "fort",
        "gallery",
        "garden",
        "grove",
        "jingu",
        "market",
        "memorial",
        "monastery",
        "mosque",
        "museum",
        "park",
        "palace",
        "pagoda",
        "shrine",
        "statue",
        "temple",
        "tower",
    }
)
_LANDMARK_SYNONYMS = {
    "dera": "temple",
    "ji": "temple",
    "jingu": "shrine",
    "jinja": "shrine",
    "taisha": "shrine",
}


class PlacesProviderUnavailableError(RuntimeError):
    """A provider-wide failure that should stop trip-local resolution calls."""


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


def place_name_variants(value: str) -> tuple[str, ...]:
    """Return conservative lookup variants for a generated landmark name."""

    clean = " ".join(value.split()).strip(" ,.!?;:")
    candidates = [clean]

    without_parenthetical = re.sub(r"\s*\([^)]*\)\s*", " ", clean).strip()
    if without_parenthetical:
        candidates.append(without_parenthetical)

    for candidate in tuple(candidates):
        words = candidate.split()
        while words and normalize_place_text(words[-1]) in _TRAILING_ACTIVITY_WORDS:
            words.pop()
        if words:
            candidates.append(" ".join(words).strip(" ,.!?;:"))

    # Split only when both halves identify landmarks. This avoids corrupting
    # proper names such as "Victoria and Albert Museum".
    for candidate in tuple(candidates):
        parts = re.split(r"\s+(?:and|&)\s+", candidate, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) != 2:
            continue
        left_tokens = set(normalize_place_text(parts[0]).split())
        right_tokens = set(normalize_place_text(parts[1]).split())
        if left_tokens & _LANDMARK_WORDS and right_tokens & _LANDMARK_WORDS:
            candidates.extend(part.strip(" ,.!?;:") for part in parts)

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = normalize_place_text(candidate)
        if normalized and normalized not in seen:
            unique.append(candidate)
            seen.add(normalized)
    return tuple(unique)


def place_name_similarity(left: str, right: str) -> float:
    """Compare landmark names across display suffixes and common aliases."""

    normalized_left = normalize_place_text(left)
    normalized_right = normalize_place_text(right)
    if not normalized_left or not normalized_right:
        return 0.0
    if normalized_left == normalized_right:
        return 1.0
    if normalized_left in normalized_right or normalized_right in normalized_left:
        return 0.9

    left_tokens = _canonical_landmark_tokens(normalized_left)
    right_tokens = _canonical_landmark_tokens(normalized_right)
    if not left_tokens or not right_tokens:
        return 0.0
    if left_tokens == right_tokens:
        return 1.0
    if left_tokens <= right_tokens or right_tokens <= left_tokens:
        return 0.9
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _canonical_landmark_tokens(value: str) -> set[str]:
    tokens = {
        _LANDMARK_SYNONYMS.get(token, token)
        for token in value.split()
        if token not in _TRAILING_ACTIVITY_WORDS
    }
    return tokens


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
