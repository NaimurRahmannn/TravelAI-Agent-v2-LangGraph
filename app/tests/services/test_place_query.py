import pytest

from app.services.places import build_place_query, normalize_place_text


def test_query_combines_name_and_location_hint():
    assert build_place_query(
        name="Wat Mahathat",
        location_hint="Ayutthaya, Thailand",
        city="Ayutthaya",
        destination="Thailand",
    ) == "Wat Mahathat, Ayutthaya, Thailand"


def test_query_deduplicates_repeated_components():
    assert build_place_query(
        name="Wat Mahathat",
        location_hint="Wat Mahathat, Ayutthaya, Thailand",
        city="Ayutthaya",
        destination="Thailand",
    ) == "Wat Mahathat, Ayutthaya, Thailand"


def test_query_falls_back_to_city_and_destination_and_ignores_whitespace():
    assert build_place_query(
        name="Erawan National Park",
        location_hint="  ",
        city=" Kanchanaburi ",
        destination=" Thailand ",
    ) == "Erawan National Park, Kanchanaburi, Thailand"


def test_query_requires_a_meaningful_component():
    with pytest.raises(ValueError):
        build_place_query(name=" ", location_hint=None, city=" ", destination=" ")


def test_normalization_is_unicode_and_punctuation_safe():
    assert normalize_place_text("  Kinkaku-ji, KYOTO ") == "kinkaku ji kyoto"
