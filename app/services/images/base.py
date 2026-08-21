from typing import Protocol

from app.models import PlaceImage, ResolvedPlace


class ImageProviderError(RuntimeError):
    """Base error for safe, internal image-provider failures."""


class ImageProviderUnavailableError(ImageProviderError):
    """A provider-wide failure that should open a trip-local circuit."""


class WikimediaRateLimitError(ImageProviderUnavailableError):
    """Wikimedia rate limiting persisted after bounded retries."""


class WikimediaAccessError(ImageProviderUnavailableError):
    """Wikimedia rejected access or the configured User-Agent."""


class PexelsRateLimitError(ImageProviderUnavailableError):
    """Pexels rate limiting persisted after bounded retries."""


class PexelsAccessError(ImageProviderUnavailableError):
    """Pexels rejected the configured API key."""


class PlaceImageProvider(Protocol):
    """Provider boundary for resolving one verified place image."""

    async def resolve_image(self, *, place: ResolvedPlace) -> PlaceImage | None:
        ...
