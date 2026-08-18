import asyncio

import httpx

from app.models import (
    Activity,
    BudgetBreakdown,
    BudgetItem,
    ItineraryDay,
    PlaceImage,
    ResolvedPlace,
    TripPlan,
)
from app.services.image_enrichment import (
    enrich_trip_images,
    image_deduplication_key,
    should_enrich_activity_image,
)
from app.services.images import ImageProviderUnavailableError
from app.services.images.wikimedia import WikimediaImageProvider


def _place(name, place_id, *, status="resolved"):
    return ResolvedPlace(
        provider="geoapify",
        provider_place_id=place_id,
        name=name,
        city="Ayutthaya",
        country="Thailand",
        latitude=14.35,
        longitude=100.56,
        resolution_status=status,
    )


def _activity(name, category, place=None):
    return Activity(
        name=name,
        category=category,
        place=place,
        place_resolution_status=place.resolution_status if place else "unresolved",
    )


def _plan(*activities):
    return TripPlan(
        title="Thailand Plan",
        destination="Thailand",
        duration_days=1,
        travelers=2,
        preferences=[],
        days=[
            ItineraryDay(
                day_number=1,
                city="Ayutthaya",
                activities=list(activities),
            )
        ],
        budget=BudgetBreakdown(
            items=[BudgetItem(category="Activities", amount_usd=100)],
            estimated_total_usd=100,
        ),
        practical_notes=[],
    )


def _image(entity_id="Q1"):
    return PlaceImage(
        provider="wikimedia_commons",
        wikidata_entity_id=entity_id,
        commons_file_title="File:Temple.jpg",
        original_url="https://upload.wikimedia.org/temple.jpg",
        thumbnail_url="https://upload.wikimedia.org/800px-temple.jpg",
        source_page_url="https://commons.wikimedia.org/wiki/File:Temple.jpg",
        author="Jane Doe",
        license_short_name="CC BY 4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        attribution_text="Jane Doe / CC BY 4.0 / Wikimedia Commons",
    )


class FakeProvider:
    def __init__(self, results=None, *, delay=0):
        self.results = results or {}
        self.delay = delay
        self.calls = []
        self.active = 0
        self.max_active = 0

    async def resolve_image(self, *, place):
        self.calls.append(place.provider_place_id)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            return self.results.get(place.provider_place_id)
        finally:
            self.active -= 1


def test_eligibility_requires_attraction_like_fully_resolved_geoapify_place():
    resolved = _place("Wat Mahathat", "wat")
    partial = _place("Partial Temple", "partial", status="partially_resolved")

    assert should_enrich_activity_image(_activity("Wat Mahathat", "history", resolved))
    assert not should_enrich_activity_image(_activity("Airport Transfer", "transport"))
    assert not should_enrich_activity_image(_activity("Lunch", "dining"))
    assert not should_enrich_activity_image(_activity("Hotel Check-in", "hotel"))
    assert not should_enrich_activity_image(_activity("Partial Temple", "history", partial))


def test_enrichment_supports_partial_success_and_preserves_original_data():
    first = _place("Wat Mahathat", "wat")
    second = _place("Erawan National Park", "erawan")
    original = _plan(
        _activity("Wat Mahathat", "history", first),
        _activity("Erawan National Park", "nature", second),
    )
    provider = FakeProvider({"wat": _image("Q1")})

    enriched = asyncio.run(enrich_trip_images(original, provider))

    assert original.days[0].activities[0].image is None
    assert enriched.days[0].activities[0].image.wikidata_entity_id == "Q1"
    assert enriched.days[0].activities[1].image is None
    assert enriched.days[0].activities[0].place == first
    assert [activity.name for activity in enriched.days[0].activities] == [
        "Wat Mahathat",
        "Erawan National Park",
    ]


def test_duplicate_geoapify_identity_calls_provider_once_and_reuses_image():
    place = _place("Wat Mahathat", "same-id")
    plan = _plan(
        _activity("Wat Mahathat morning", "history", place),
        _activity("Wat Mahathat sunset", "history", place),
    )
    provider = FakeProvider({"same-id": _image()})

    enriched = asyncio.run(enrich_trip_images(plan, provider))

    assert provider.calls == ["same-id"]
    assert all(activity.image is not None for activity in enriched.days[0].activities)
    assert image_deduplication_key(place) == "geoapify|same-id"


def test_ineligible_activities_never_reach_provider():
    plan = _plan(
        _activity("Wat Mahathat", "history", _place("Wat Mahathat", "wat")),
        _activity("Airport Transfer", "transport"),
        _activity("Lunch", "food"),
    )
    provider = FakeProvider({"wat": _image()})

    enriched = asyncio.run(enrich_trip_images(plan, provider))

    assert provider.calls == ["wat"]
    assert enriched.days[0].activities[0].image is not None
    assert all(activity.image is None for activity in enriched.days[0].activities[1:])


class UnavailableProvider:
    def __init__(self):
        self.calls = []

    async def resolve_image(self, *, place):
        self.calls.append(place.provider_place_id)
        raise ImageProviderUnavailableError("outage")


def test_provider_wide_failure_opens_trip_local_circuit_after_probe():
    places = [_place(f"Place {index}", f"id-{index}") for index in range(3)]
    plan = _plan(*[_activity(place.name, "visit", place) for place in places])
    provider = UnavailableProvider()

    enriched = asyncio.run(enrich_trip_images(plan, provider, concurrency_limit=3))

    assert provider.calls == ["id-0"]
    assert all(activity.image is None for activity in enriched.days[0].activities)


def test_retryable_http_outage_is_not_multiplied_by_activity_count():
    request_count = 0

    def handler(request):
        nonlocal request_count
        request_count += 1
        return httpx.Response(503)

    async def run():
        places = [_place(f"Place {index}", f"id-{index}") for index in range(3)]
        plan = _plan(*[_activity(place.name, "visit", place) for place in places])
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = WikimediaImageProvider(
                "TravelAI/1.0 (https://example.test/support)",
                client=client,
                sleep=lambda _: asyncio.sleep(0),
            )
            return await enrich_trip_images(plan, provider, concurrency_limit=3)

    enriched = asyncio.run(run())

    assert request_count == 3
    assert all(activity.image is None for activity in enriched.days[0].activities)


def test_no_image_result_does_not_open_circuit():
    places = [_place(f"Place {index}", f"id-{index}") for index in range(2)]
    plan = _plan(*[_activity(place.name, "visit", place) for place in places])
    provider = FakeProvider({"id-1": _image("Q2")})

    enriched = asyncio.run(enrich_trip_images(plan, provider))

    assert provider.calls == ["id-0", "id-1"]
    assert enriched.days[0].activities[0].image is None
    assert enriched.days[0].activities[1].image.wikidata_entity_id == "Q2"


def test_concurrency_is_bounded_after_probe_and_order_is_stable():
    places = [_place(f"Place {index}", f"id-{index}") for index in range(3)]
    plan = _plan(*[_activity(place.name, "visit", place) for place in places])
    provider = FakeProvider(
        {place.provider_place_id: _image(f"Q{index + 1}") for index, place in enumerate(places)},
        delay=0.01,
    )

    enriched = asyncio.run(enrich_trip_images(plan, provider, concurrency_limit=2))

    assert 1 < provider.max_active <= 2
    assert [activity.name for activity in enriched.days[0].activities] == [
        "Place 0",
        "Place 1",
        "Place 2",
    ]
