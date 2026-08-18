import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import math
import re
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from app.core.logging import get_logger
from app.models import PlaceImage, ResolvedPlace
from app.services.images.base import (
    ImageProviderError,
    ImageProviderUnavailableError,
    WikimediaAccessError,
    WikimediaRateLimitError,
)
from app.services.images.license_policy import (
    build_attribution_text,
    is_supported_license,
)
from app.services.places import normalize_place_text

logger = get_logger(__name__)

WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"
COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"
WIKIDATA_RESULT_LIMIT = 5
COMMONS_THUMBNAIL_WIDTH = 800
MAX_REQUEST_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 0.25
MAX_RETRY_AFTER_SECONDS = 5.0

VERY_CLOSE_DISTANCE_KM = 2.0
PLAUSIBLE_DISTANCE_KM = 25.0
MAX_LOCATION_MISMATCH_KM = 100.0
MINIMUM_NAME_SIMILARITY = 0.75
STRONG_NAME_SIMILARITY = 0.90

_ENTITY_ID_PATTERN = re.compile(r"^Q[1-9][0-9]*$")
_WIKIMEDIA_UPLOAD_HOSTS = frozenset({"upload.wikimedia.org"})
_COMMONS_PAGE_HOSTS = frozenset({"commons.wikimedia.org"})


@dataclass(frozen=True)
class WikidataCandidate:
    """Small deterministic view of a Wikidata entity candidate."""

    entity_id: str
    label: str
    aliases: tuple[str, ...] = ()
    description: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    p18_file_title: str | None = None


@dataclass(frozen=True)
class _ScoredCandidate:
    candidate: WikidataCandidate
    score: float
    name_similarity: float
    distance_km: float | None
    country_match: bool
    locality_match: bool


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.casefold() in {"script", "style"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


def html_to_plain_text(value: object) -> str | None:
    """Convert Wikimedia's small HTML metadata fragments to normalized text."""

    if value is None:
        return None
    parser = _PlainTextParser()
    try:
        parser.feed(str(value))
        parser.close()
    except Exception:
        return None
    normalized = " ".join(" ".join(parser.parts).split())
    return normalized or None


def distance_km(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    """Return great-circle distance between coordinates using Haversine."""

    radius_km = 6371.0088
    lat_a, lat_b = math.radians(latitude_a), math.radians(latitude_b)
    delta_lat = lat_b - lat_a
    delta_lon = math.radians(longitude_b - longitude_a)
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2) ** 2
    )
    return radius_km * 2 * math.asin(min(1.0, math.sqrt(haversine)))


def select_wikidata_candidate(
    candidates: Sequence[WikidataCandidate],
    *,
    place: ResolvedPlace,
) -> WikidataCandidate | None:
    """Select a candidate only when identity and location signals agree."""

    accepted: list[_ScoredCandidate] = []
    for candidate in candidates:
        scored = _score_candidate(candidate, place=place)
        if scored is not None and _candidate_is_acceptable(scored):
            accepted.append(scored)
    if not accepted:
        return None
    strongest = max(
        accepted,
        key=lambda item: (
            item.score,
            item.name_similarity,
            -(item.distance_km if item.distance_km is not None else math.inf),
            bool(item.candidate.p18_file_title),
            item.candidate.entity_id,
        ),
    )
    return strongest.candidate


def select_p18_file(claims: object) -> str | None:
    """Select a non-deprecated P18 filename by rank then stable title order."""

    if not isinstance(claims, list):
        return None
    ranked: list[tuple[int, str]] = []
    for claim in claims:
        if not isinstance(claim, Mapping) or claim.get("rank") == "deprecated":
            continue
        mainsnak = claim.get("mainsnak")
        if not isinstance(mainsnak, Mapping) or mainsnak.get("snaktype") != "value":
            continue
        datavalue = mainsnak.get("datavalue")
        value = datavalue.get("value") if isinstance(datavalue, Mapping) else None
        if not isinstance(value, str):
            continue
        filename = " ".join(value.split())
        if not filename or any(ord(character) < 32 for character in filename):
            continue
        if filename.casefold().startswith("file:"):
            filename = filename[5:].strip()
        if not filename:
            continue
        rank = 0 if claim.get("rank") == "preferred" else 1
        ranked.append((rank, filename))
    if not ranked:
        return None
    _, filename = min(ranked, key=lambda item: (item[0], item[1].casefold()))
    return f"File:{filename}"


class WikimediaImageProvider:
    """Resolve Geoapify-backed places through Wikidata and Commons."""

    def __init__(
        self,
        user_agent: str,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not user_agent.strip():
            raise ValueError("A descriptive Wikimedia User-Agent is required")
        self._user_agent = user_agent.strip()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=3.0, read=7.0),
        )
        self._sleep = sleep

    async def resolve_image(self, *, place: ResolvedPlace) -> PlaceImage | None:
        logger.info(
            "image_resolution_started provider_place_id=%s activity=%s",
            place.provider_place_id,
            place.name,
        )
        candidates = await self._find_candidates(place.name)
        selected = select_wikidata_candidate(candidates, place=place)
        if selected is None:
            logger.info(
                "image_resolution_unresolved provider_place_id=%s reason=no_entity",
                place.provider_place_id,
            )
            return None
        if selected.p18_file_title is None:
            logger.info(
                "image_resolution_unresolved provider_place_id=%s wikidata_id=%s "
                "reason=no_p18",
                place.provider_place_id,
                selected.entity_id,
            )
            return None

        image = await self._fetch_commons_image(
            entity_id=selected.entity_id,
            file_title=selected.p18_file_title,
        )
        logger.info(
            "image_resolution_%s provider_place_id=%s wikidata_id=%s",
            "resolved" if image is not None else "unresolved",
            place.provider_place_id,
            selected.entity_id,
        )
        return image

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _find_candidates(self, name: str) -> list[WikidataCandidate]:
        search_payload = await self._request_json(
            WIKIDATA_API_URL,
            params={
                "action": "wbsearchentities",
                "search": name,
                "language": "en",
                "uselang": "en",
                "type": "item",
                "limit": WIKIDATA_RESULT_LIMIT,
                "format": "json",
            },
        )
        search_results = search_payload.get("search")
        if not isinstance(search_results, list):
            raise ImageProviderUnavailableError(
                "Wikidata search returned an unexpected payload"
            )

        search_by_id: dict[str, Mapping[str, Any]] = {}
        for item in search_results:
            if not isinstance(item, Mapping):
                continue
            entity_id = item.get("id")
            if isinstance(entity_id, str) and _ENTITY_ID_PATTERN.fullmatch(entity_id):
                search_by_id.setdefault(entity_id, item)
        if not search_by_id:
            return []

        entity_payload = await self._request_json(
            WIKIDATA_API_URL,
            params={
                "action": "wbgetentities",
                "ids": "|".join(search_by_id),
                "props": "labels|descriptions|aliases|claims",
                "languages": "en",
                "languagefallback": 1,
                "format": "json",
            },
        )
        entities = entity_payload.get("entities")
        if not isinstance(entities, Mapping):
            raise ImageProviderUnavailableError(
                "Wikidata entities returned an unexpected payload"
            )
        candidates: list[WikidataCandidate] = []
        for entity_id, search_result in search_by_id.items():
            entity = entities.get(entity_id)
            if not isinstance(entity, Mapping) or entity.get("missing") is not None:
                continue
            candidate = _to_candidate(entity_id, entity, search_result)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    async def _fetch_commons_image(
        self,
        *,
        entity_id: str,
        file_title: str,
    ) -> PlaceImage | None:
        payload = await self._request_json(
            COMMONS_API_URL,
            params={
                "action": "query",
                "prop": "imageinfo",
                "titles": file_title,
                "iiprop": "url|size|extmetadata",
                "iiurlwidth": COMMONS_THUMBNAIL_WIDTH,
                "iiextmetadatalanguage": "en",
                "iiextmetadatafilter": (
                    "Artist|Credit|LicenseShortName|LicenseUrl|UsageTerms|"
                    "ImageDescription"
                ),
                "format": "json",
                "formatversion": 2,
            },
        )
        image = _parse_commons_image(
            payload,
            entity_id=entity_id,
            requested_file_title=file_title,
        )
        if image is None:
            logger.info(
                "image_resolution_license_or_metadata_rejected wikidata_id=%s "
                "commons_file=%s",
                entity_id,
                file_title,
            )
        return image

    async def _request_json(
        self,
        url: str,
        *,
        params: Mapping[str, object],
    ) -> Mapping[str, Any]:
        for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
            try:
                response = await self._client.get(
                    url,
                    params=params,
                    headers={"User-Agent": self._user_agent},
                )
            except httpx.TransportError as exc:
                if attempt < MAX_REQUEST_ATTEMPTS:
                    await self._sleep(RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)))
                    continue
                raise ImageProviderUnavailableError(
                    "Wikimedia request failed"
                ) from exc

            if response.status_code in {401, 403}:
                raise WikimediaAccessError("Wikimedia rejected provider access")
            if response.status_code == 429:
                if attempt < MAX_REQUEST_ATTEMPTS:
                    await self._sleep(_retry_delay(response, attempt))
                    continue
                raise WikimediaRateLimitError("Wikimedia rate limit exceeded")
            if 500 <= response.status_code < 600:
                if attempt < MAX_REQUEST_ATTEMPTS:
                    await self._sleep(_retry_delay(response, attempt))
                    continue
                raise ImageProviderUnavailableError(
                    "Wikimedia service unavailable"
                )
            if response.status_code >= 400:
                raise ImageProviderError(
                    f"Wikimedia request rejected with status {response.status_code}"
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise ImageProviderUnavailableError(
                    "Wikimedia returned invalid JSON"
                ) from exc
            if not isinstance(payload, Mapping):
                raise ImageProviderUnavailableError(
                    "Wikimedia returned an unexpected payload"
                )
            api_error = payload.get("error")
            if isinstance(api_error, Mapping):
                error_code = _string(api_error.get("code")).casefold()
                if error_code in {"ratelimited", "maxlag", "readonly"}:
                    if attempt < MAX_REQUEST_ATTEMPTS:
                        await self._sleep(_retry_delay(response, attempt))
                        continue
                    if error_code == "ratelimited":
                        raise WikimediaRateLimitError(
                            "Wikimedia API rate limit exceeded"
                        )
                    raise ImageProviderUnavailableError(
                        "Wikimedia API is temporarily unavailable"
                    )
                if error_code in {"permissiondenied", "badaccess"}:
                    raise WikimediaAccessError("Wikimedia rejected provider access")
                raise ImageProviderError("Wikimedia API rejected the request")
            return payload

        raise ImageProviderUnavailableError("Wikimedia request failed")


def _score_candidate(
    candidate: WikidataCandidate,
    *,
    place: ResolvedPlace,
) -> _ScoredCandidate | None:
    names = (candidate.label, *candidate.aliases)
    name_similarity = max((_text_similarity(place.name, name) for name in names), default=0)
    if name_similarity < MINIMUM_NAME_SIMILARITY:
        return None

    location_text = " ".join(
        part
        for part in (candidate.description, candidate.country)
        if part
    )
    country_match = _contains_location(location_text, place.country)
    locality_match = any(
        _contains_location(location_text, expected)
        for expected in (place.city, place.state)
        if expected
    )
    if (
        candidate.country
        and place.country
        and normalize_place_text(candidate.country) != normalize_place_text(place.country)
    ):
        return None

    candidate_distance = None
    if candidate.latitude is not None and candidate.longitude is not None:
        candidate_distance = distance_km(
            place.latitude,
            place.longitude,
            candidate.latitude,
            candidate.longitude,
        )
        if candidate_distance > MAX_LOCATION_MISMATCH_KM:
            return None

    distance_score = _distance_score(candidate_distance)
    score = (
        0.55 * name_similarity
        + 0.30 * distance_score
        + 0.10 * float(country_match)
        + 0.05 * float(locality_match)
    )
    return _ScoredCandidate(
        candidate=candidate,
        score=score,
        name_similarity=name_similarity,
        distance_km=candidate_distance,
        country_match=country_match,
        locality_match=locality_match,
    )


def _candidate_is_acceptable(candidate: _ScoredCandidate) -> bool:
    if candidate.distance_km is not None:
        if candidate.distance_km <= PLAUSIBLE_DISTANCE_KM:
            return True
        return (
            candidate.name_similarity >= STRONG_NAME_SIMILARITY
            and (candidate.country_match or candidate.locality_match)
        )
    return (
        candidate.name_similarity >= STRONG_NAME_SIMILARITY
        and candidate.country_match
        and candidate.locality_match
    )


def _distance_score(value: float | None) -> float:
    if value is None:
        return 0.0
    if value <= VERY_CLOSE_DISTANCE_KM:
        return 1.0
    if value <= PLAUSIBLE_DISTANCE_KM:
        return 0.75
    if value <= MAX_LOCATION_MISMATCH_KM:
        return 0.25
    return 0.0


def _text_similarity(left: str, right: str) -> float:
    normalized_left = normalize_place_text(left)
    normalized_right = normalize_place_text(right)
    if not normalized_left or not normalized_right:
        return 0.0
    if normalized_left == normalized_right:
        return 1.0
    if normalized_left in normalized_right or normalized_right in normalized_left:
        return 0.9
    left_tokens = set(normalized_left.split())
    right_tokens = set(normalized_right.split())
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _contains_location(text: str, expected: str | None) -> bool:
    normalized_text = normalize_place_text(text)
    normalized_expected = normalize_place_text(expected)
    return bool(normalized_expected and normalized_expected in normalized_text)


def _to_candidate(
    entity_id: str,
    entity: Mapping[str, Any],
    search_result: Mapping[str, Any],
) -> WikidataCandidate | None:
    label = _localized_value(entity.get("labels"), "en") or _string(
        search_result.get("label")
    )
    if not label:
        return None
    description = _localized_value(entity.get("descriptions"), "en") or _string(
        search_result.get("description")
    )
    aliases = _aliases(entity.get("aliases"), "en")
    search_aliases = search_result.get("aliases")
    if isinstance(search_aliases, list):
        aliases = tuple(dict.fromkeys((*aliases, *map(_string, search_aliases))))
    claims = entity.get("claims")
    claims = claims if isinstance(claims, Mapping) else {}
    latitude, longitude = _coordinate_from_claims(claims.get("P625"))
    return WikidataCandidate(
        entity_id=entity_id,
        label=label,
        aliases=tuple(alias for alias in aliases if alias),
        description=description or None,
        latitude=latitude,
        longitude=longitude,
        p18_file_title=select_p18_file(claims.get("P18")),
    )


def _coordinate_from_claims(claims: object) -> tuple[float | None, float | None]:
    if not isinstance(claims, list):
        return None, None
    ordered = sorted(
        (claim for claim in claims if isinstance(claim, Mapping)),
        key=lambda claim: 0 if claim.get("rank") == "preferred" else 1,
    )
    for claim in ordered:
        if claim.get("rank") == "deprecated":
            continue
        mainsnak = claim.get("mainsnak")
        datavalue = mainsnak.get("datavalue") if isinstance(mainsnak, Mapping) else None
        value = datavalue.get("value") if isinstance(datavalue, Mapping) else None
        if not isinstance(value, Mapping):
            continue
        try:
            latitude = float(value["latitude"])
            longitude = float(value["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if -90 <= latitude <= 90 and -180 <= longitude <= 180:
            return latitude, longitude
    return None, None


def _localized_value(value: object, language: str) -> str:
    if not isinstance(value, Mapping):
        return ""
    selected = value.get(language)
    if not isinstance(selected, Mapping):
        selected = next(
            (item for item in value.values() if isinstance(item, Mapping)),
            None,
        )
    return _string(selected.get("value")) if isinstance(selected, Mapping) else ""


def _aliases(value: object, language: str) -> tuple[str, ...]:
    if not isinstance(value, Mapping):
        return ()
    selected = value.get(language)
    if not isinstance(selected, list):
        return ()
    return tuple(
        _string(item.get("value"))
        for item in selected
        if isinstance(item, Mapping) and _string(item.get("value"))
    )


def _parse_commons_image(
    payload: Mapping[str, Any],
    *,
    entity_id: str,
    requested_file_title: str,
) -> PlaceImage | None:
    query = payload.get("query")
    pages = query.get("pages") if isinstance(query, Mapping) else None
    if isinstance(pages, Mapping):
        pages = list(pages.values())
    if not isinstance(pages, list) or not pages:
        return None
    page = next((item for item in pages if isinstance(item, Mapping)), None)
    if page is None or page.get("missing") is not None:
        return None
    imageinfo = page.get("imageinfo")
    if not isinstance(imageinfo, list) or not imageinfo:
        return None
    info = imageinfo[0]
    if not isinstance(info, Mapping):
        return None

    original_url = _trusted_url(info.get("url"), _WIKIMEDIA_UPLOAD_HOSTS)
    thumbnail_url = _trusted_url(info.get("thumburl"), _WIKIMEDIA_UPLOAD_HOSTS)
    source_page_url = _trusted_url(info.get("descriptionurl"), _COMMONS_PAGE_HOSTS)
    if original_url is None or source_page_url is None:
        return None

    metadata = info.get("extmetadata")
    if not isinstance(metadata, Mapping):
        return None
    author = _metadata_text(metadata, "Artist")
    credit = _metadata_text(metadata, "Credit")
    license_short_name = _metadata_text(metadata, "LicenseShortName")
    if not is_supported_license(license_short_name):
        return None
    try:
        attribution = build_attribution_text(
            author=author,
            license_short_name=license_short_name or "",
        )
        return PlaceImage(
            provider="wikimedia_commons",
            wikidata_entity_id=entity_id,
            commons_file_title=_string(page.get("title")) or requested_file_title,
            original_url=original_url,
            thumbnail_url=thumbnail_url,
            source_page_url=source_page_url,
            width=_positive_int(info.get("width")),
            height=_positive_int(info.get("height")),
            author=author,
            credit=credit,
            license_short_name=license_short_name or "",
            license_url=_metadata_url(metadata, "LicenseUrl"),
            usage_terms=_metadata_text(metadata, "UsageTerms"),
            attribution_text=attribution,
            description=_metadata_text(metadata, "ImageDescription"),
        )
    except (ValidationError, ValueError):
        return None


def _metadata_text(metadata: Mapping[str, Any], key: str) -> str | None:
    item = metadata.get(key)
    value = item.get("value") if isinstance(item, Mapping) else None
    return html_to_plain_text(value)


def _metadata_url(metadata: Mapping[str, Any], key: str) -> str | None:
    value = _metadata_text(metadata, key)
    if value is None:
        return None
    parsed = urlsplit(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else None


def _trusted_url(value: object, hosts: frozenset[str]) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    parsed = urlsplit(normalized)
    return (
        normalized
        if parsed.scheme in {"http", "https"} and parsed.hostname in hosts
        else None
    )


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 1 else None


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            delay = float(retry_after)
        except ValueError:
            try:
                when = parsedate_to_datetime(retry_after)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=UTC)
                delay = (when - datetime.now(UTC)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                delay = -1
        if 0 <= delay <= MAX_RETRY_AFTER_SECONDS:
            return delay
    return RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))


def _string(value: object) -> str:
    return str(value).strip() if value is not None else ""
