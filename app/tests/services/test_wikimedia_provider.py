import asyncio

import httpx
import pytest

from app.models import ResolvedPlace
from app.services.images import (
    ImageProviderUnavailableError,
    WikimediaAccessError,
    WikimediaRateLimitError,
)
from app.services.images.license_policy import (
    build_attribution_text,
    is_supported_license,
)
from app.services.images.wikimedia import (
    WikidataCandidate,
    WikimediaImageProvider,
    _parse_commons_image,
    distance_km,
    html_to_plain_text,
    select_p18_file,
    select_wikidata_candidate,
)


def _place(**updates) -> ResolvedPlace:
    data = {
        "provider": "geoapify",
        "provider_place_id": "geo-wat-mahathat",
        "name": "Wat Mahathat",
        "city": "Ayutthaya",
        "state": "Phra Nakhon Si Ayutthaya",
        "country": "Thailand",
        "country_code": "th",
        "latitude": 14.3569,
        "longitude": 100.5683,
        "resolution_status": "resolved",
    }
    data.update(updates)
    return ResolvedPlace.model_validate(data)


def _claim(value, *, rank="normal", property_id="P18"):
    return {
        "rank": rank,
        "mainsnak": {
            "property": property_id,
            "snaktype": "value",
            "datavalue": {"value": value},
        },
    }


def _commons_payload(*, license_name="CC BY-SA 4.0", author="Jane Doe"):
    return {
        "query": {
            "pages": [
                {
                    "pageid": 1,
                    "title": "File:Wat Mahathat.jpg",
                    "imageinfo": [
                        {
                            "url": "https://upload.wikimedia.org/example/original.jpg",
                            "thumburl": "https://upload.wikimedia.org/example/800px.jpg",
                            "descriptionurl": (
                                "https://commons.wikimedia.org/wiki/"
                                "File:Wat_Mahathat.jpg"
                            ),
                            "width": 4000,
                            "height": 3000,
                            "extmetadata": {
                                "Artist": {"value": f"<a>{author}</a>"},
                                "Credit": {"value": "Own &amp; archival work"},
                                "LicenseShortName": {"value": license_name},
                                "LicenseUrl": {
                                    "value": "https://creativecommons.org/licenses/by-sa/4.0/"
                                },
                                "UsageTerms": {
                                    "value": "Creative Commons Attribution-ShareAlike"
                                },
                                "ImageDescription": {
                                    "value": "<b>Wat Mahathat</b> at sunrise"
                                },
                            },
                        }
                    ],
                }
            ]
        }
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('<a href="https://example.test">Jane Doe</a>', "Jane Doe"),
        ("A &amp; B", "A & B"),
        ("<b>A <i>nested</i> value</b>", "A nested value"),
        (" <span> spaced   text </span> ", "spaced text"),
        ("<script>bad()</script>", None),
        ("", None),
    ],
)
def test_html_metadata_is_sanitized_to_plain_text(raw, expected):
    assert html_to_plain_text(raw) == expected


@pytest.mark.parametrize(
    "license_name",
    ["CC0", "CC0 1.0", "Public Domain", "CC BY 4.0", "CC BY-SA 3.0"],
)
def test_reusable_license_policy_accepts_allowlisted_values(license_name):
    assert is_supported_license(license_name) is True


@pytest.mark.parametrize(
    "license_name",
    [None, "", "CC BY-NC 4.0", "CC BY-ND 4.0", "All rights reserved", "Unknown"],
)
def test_reusable_license_policy_rejects_unknown_or_restricted_values(license_name):
    assert is_supported_license(license_name) is False


def test_attribution_requires_author_for_attribution_license():
    with pytest.raises(ValueError):
        build_attribution_text(author=None, license_short_name="CC BY 4.0")

    assert build_attribution_text(
        author=None,
        license_short_name="CC0 1.0",
    ) == "CC0 1.0 / Wikimedia Commons"


def test_haversine_distance_has_expected_scale():
    assert distance_km(14.0, 100.0, 14.0, 100.0) == pytest.approx(0)
    assert 1 < distance_km(14.0, 100.0, 14.02, 100.0) < 3
    assert distance_km(14.0, 100.0, 35.0, 135.0) > 3000


def test_candidate_selection_uses_identity_and_proximity_not_result_order():
    candidates = [
        WikidataCandidate(
            entity_id="Q2",
            label="Wat Mahathat",
            description="Buddhist temple in another province, Thailand",
            latitude=17.0,
            longitude=102.0,
            p18_file_title="File:Wrong.jpg",
        ),
        WikidataCandidate(
            entity_id="Q1",
            label="Wat Mahathat",
            description="Buddhist temple in Ayutthaya, Thailand",
            latitude=14.3568,
            longitude=100.5682,
            p18_file_title="File:Correct.jpg",
        ),
    ]

    selected = select_wikidata_candidate(candidates, place=_place())

    assert selected is not None
    assert selected.entity_id == "Q1"


def test_candidate_selection_rejects_wrong_country_weak_name_and_far_entity():
    wrong_country = WikidataCandidate(
        entity_id="Q1",
        label="Wat Mahathat",
        description="Buddhist temple in Laos",
        country="Laos",
    )
    weak_nearby = WikidataCandidate(
        entity_id="Q2",
        label="Riverside History Museum",
        latitude=14.3568,
        longitude=100.5682,
    )
    far = WikidataCandidate(
        entity_id="Q3",
        label="Wat Mahathat",
        description="Buddhist temple in Thailand",
        latitude=7.0,
        longitude=99.0,
    )

    assert (
        select_wikidata_candidate(
            [wrong_country, weak_nearby, far],
            place=_place(),
        )
        is None
    )


def test_candidate_without_coordinates_needs_country_and_locality_support():
    supported = WikidataCandidate(
        entity_id="Q1",
        label="Wat Mahathat",
        description="Buddhist temple in Ayutthaya, Thailand",
    )
    unsupported = WikidataCandidate(
        entity_id="Q2",
        label="Wat Mahathat",
        description="Buddhist temple",
        p18_file_title="File:Available.jpg",
    )

    assert select_wikidata_candidate([unsupported], place=_place()) is None
    assert select_wikidata_candidate([supported], place=_place()) == supported


def test_p18_prefers_preferred_rank_and_uses_stable_order():
    claims = [
        _claim("Normal.jpg"),
        _claim("Z preferred.jpg", rank="preferred"),
        _claim("A preferred.jpg", rank="preferred"),
        _claim("Deprecated.jpg", rank="deprecated"),
    ]

    assert select_p18_file(claims) == "File:A preferred.jpg"


@pytest.mark.parametrize(
    "claims",
    [None, [], [{}], [_claim(None)], [_claim("Old.jpg", rank="deprecated")]],
)
def test_p18_rejects_missing_or_malformed_claims(claims):
    assert select_p18_file(claims) is None


def test_commons_metadata_builds_attribution_ready_image():
    image = _parse_commons_image(
        _commons_payload(),
        entity_id="Q660585",
        requested_file_title="File:Wat Mahathat.jpg",
    )

    assert image is not None
    assert image.wikidata_entity_id == "Q660585"
    assert image.thumbnail_url.endswith("800px.jpg")
    assert image.width == 4000
    assert image.author == "Jane Doe"
    assert image.credit == "Own & archival work"
    assert image.description == "Wat Mahathat at sunrise"
    assert image.attribution_text == (
        "Jane Doe / CC BY-SA 4.0 / Wikimedia Commons"
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"query": {"pages": []}},
        {"query": {"pages": [{"title": "File:X.jpg"}]}},
        _commons_payload(license_name="CC BY-NC 4.0"),
        _commons_payload(author=""),
    ],
)
def test_incomplete_or_unsupported_commons_metadata_is_rejected(payload):
    assert (
        _parse_commons_image(
            payload,
            entity_id="Q1",
            requested_file_title="File:X.jpg",
        )
        is None
    )


def test_commons_rejects_non_wikimedia_primary_urls():
    payload = _commons_payload()
    payload["query"]["pages"][0]["imageinfo"][0]["url"] = (
        "https://attacker.example/image.jpg"
    )

    assert (
        _parse_commons_image(
            payload,
            entity_id="Q1",
            requested_file_title="File:X.jpg",
        )
        is None
    )


def test_provider_resolves_wikidata_p18_and_commons_with_user_agent():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        action = request.url.params.get("action")
        if action == "wbsearchentities":
            return httpx.Response(
                200,
                json={
                    "search": [
                        {
                            "id": "Q660585",
                            "label": "Wat Mahathat",
                            "description": "Buddhist temple in Ayutthaya, Thailand",
                        }
                    ]
                },
            )
        if action == "wbgetentities":
            return httpx.Response(
                200,
                json={
                    "entities": {
                        "Q660585": {
                            "labels": {"en": {"value": "Wat Mahathat"}},
                            "descriptions": {
                                "en": {
                                    "value": "Buddhist temple in Ayutthaya, Thailand"
                                }
                            },
                            "aliases": {"en": [{"value": "Mahathat Temple"}]},
                            "claims": {
                                "P625": [
                                    _claim(
                                        {
                                            "latitude": 14.3568,
                                            "longitude": 100.5682,
                                        },
                                        property_id="P625",
                                    )
                                ],
                                "P18": [_claim("Wat Mahathat.jpg")],
                            },
                        }
                    }
                },
            )
        assert action == "query"
        assert request.url.params.get("iiurlwidth") == "800"
        return httpx.Response(200, json=_commons_payload())

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            provider = WikimediaImageProvider(
                "TravelAI/1.0 (https://example.test/support)",
                client=client,
                sleep=lambda _: asyncio.sleep(0),
            )
            return await provider.resolve_image(place=_place())

    image = asyncio.run(run())

    assert image is not None
    assert image.commons_file_title == "File:Wat Mahathat.jpg"
    assert len(requests) == 3
    assert all(
        request.headers["User-Agent"]
        == "TravelAI/1.0 (https://example.test/support)"
        for request in requests
    )
    assert requests[0].url.params.get("search") == "Wat Mahathat"


@pytest.mark.parametrize(
    ("status_code", "expected_error", "expected_requests"),
    [
        (403, WikimediaAccessError, 1),
        (429, WikimediaRateLimitError, 3),
        (500, ImageProviderUnavailableError, 3),
        (503, ImageProviderUnavailableError, 3),
    ],
)
def test_provider_http_failures_are_bounded(
    status_code,
    expected_error,
    expected_requests,
):
    request_count = 0

    def handler(request):
        nonlocal request_count
        request_count += 1
        return httpx.Response(status_code, headers={"Retry-After": "0"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = WikimediaImageProvider(
                "TravelAI/1.0 (https://example.test/support)",
                client=client,
                sleep=lambda _: asyncio.sleep(0),
            )
            await provider.resolve_image(place=_place())

    with pytest.raises(expected_error):
        asyncio.run(run())
    assert request_count == expected_requests


def test_transient_failure_followed_by_success_is_retried():
    request_count = 0

    def handler(request):
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"search": []})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = WikimediaImageProvider(
                "TravelAI/1.0 (https://example.test/support)",
                client=client,
                sleep=lambda _: asyncio.sleep(0),
            )
            return await provider.resolve_image(place=_place())

    assert asyncio.run(run()) is None
    assert request_count == 2


def test_http_200_mediawiki_outage_error_is_retried_and_classified():
    request_count = 0

    def handler(request):
        nonlocal request_count
        request_count += 1
        return httpx.Response(
            200,
            json={"error": {"code": "maxlag", "info": "server lag"}},
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = WikimediaImageProvider(
                "TravelAI/1.0 (https://example.test/support)",
                client=client,
                sleep=lambda _: asyncio.sleep(0),
            )
            await provider.resolve_image(place=_place())

    with pytest.raises(ImageProviderUnavailableError):
        asyncio.run(run())
    assert request_count == 3


def test_provider_transport_failure_retries_then_raises_unavailable():
    request_count = 0

    def handler(request):
        nonlocal request_count
        request_count += 1
        raise httpx.ConnectError("offline", request=request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = WikimediaImageProvider(
                "TravelAI/1.0 (https://example.test/support)",
                client=client,
                sleep=lambda _: asyncio.sleep(0),
            )
            await provider.resolve_image(place=_place())

    with pytest.raises(ImageProviderUnavailableError):
        asyncio.run(run())
    assert request_count == 3


def test_provider_timeout_retries_then_raises_unavailable():
    request_count = 0

    def handler(request):
        nonlocal request_count
        request_count += 1
        raise httpx.ReadTimeout("timed out", request=request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = WikimediaImageProvider(
                "TravelAI/1.0 (https://example.test/support)",
                client=client,
                sleep=lambda _: asyncio.sleep(0),
            )
            await provider.resolve_image(place=_place())

    with pytest.raises(ImageProviderUnavailableError):
        asyncio.run(run())
    assert request_count == 3


def test_provider_malformed_json_raises_unavailable_without_live_request():
    def handler(request):
        return httpx.Response(200, content=b"not-json")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = WikimediaImageProvider(
                "TravelAI/1.0 (https://example.test/support)",
                client=client,
            )
            await provider.resolve_image(place=_place())

    with pytest.raises(ImageProviderUnavailableError):
        asyncio.run(run())
