from enum import Enum


class PreferenceTag(str, Enum):
    """Controlled traveler-interest tags used by generated activities."""

    TEMPLES = "temples"
    FOOD = "food"
    NATURE = "nature"
    MOUNTAINS = "mountains"
    RIVERS = "rivers"
    MUSEUMS = "museums"
    SHOPPING = "shopping"
    NIGHTLIFE = "nightlife"
    BEACHES = "beaches"
    HISTORY = "history"
    CULTURE = "culture"


PREFERENCE_ALIASES: dict[str, str] = {
    "temple": PreferenceTag.TEMPLES.value,
    "temples": PreferenceTag.TEMPLES.value,
    "cuisine": PreferenceTag.FOOD.value,
    "food": PreferenceTag.FOOD.value,
    "nature": PreferenceTag.NATURE.value,
    "garden": PreferenceTag.NATURE.value,
    "gardens": PreferenceTag.NATURE.value,
    "park": PreferenceTag.NATURE.value,
    "parks": PreferenceTag.NATURE.value,
    "hiking": PreferenceTag.NATURE.value,
    "mountain": PreferenceTag.MOUNTAINS.value,
    "mountains": PreferenceTag.MOUNTAINS.value,
    "river": PreferenceTag.RIVERS.value,
    "rivers": PreferenceTag.RIVERS.value,
    "museum": PreferenceTag.MUSEUMS.value,
    "museums": PreferenceTag.MUSEUMS.value,
    "shopping": PreferenceTag.SHOPPING.value,
    "nightlife": PreferenceTag.NIGHTLIFE.value,
    "beach": PreferenceTag.BEACHES.value,
    "beaches": PreferenceTag.BEACHES.value,
    "history": PreferenceTag.HISTORY.value,
    "culture": PreferenceTag.CULTURE.value,
}


def normalize_preference(value: str) -> str:
    """Normalize known preference aliases while preserving unknown interests."""

    normalized = " ".join(value.strip().casefold().split())
    return PREFERENCE_ALIASES.get(normalized, normalized)


def preference_tag_for(value: str) -> PreferenceTag | None:
    """Return a controlled tag for a known preference value."""

    normalized = normalize_preference(value)
    try:
        return PreferenceTag(normalized)
    except ValueError:
        return None
