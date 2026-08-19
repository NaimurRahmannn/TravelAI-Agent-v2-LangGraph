SUPPORTED_LICENSES = frozenset(
    {
        "cc0",
        "cc0 1.0",
        "public domain",
        "public domain mark",
        "public domain mark 1.0",
        "cc by",
        "cc by 1.0",
        "cc by 2.0",
        "cc by 2.5",
        "cc by 3.0",
        "cc by 4.0",
        "cc by-sa",
        "cc by-sa 1.0",
        "cc by-sa 2.0",
        "cc by-sa 2.5",
        "cc by-sa 3.0",
        "cc by-sa 4.0",
    }
)


def normalize_license_name(value: str | None) -> str:
    """Normalize a Wikimedia license label for exact allowlist matching."""

    if not value:
        return ""
    normalized = value.casefold()
    for character in ("\N{HYPHEN}", "\N{NON-BREAKING HYPHEN}", "\N{EN DASH}"):
        normalized = normalized.replace(character, "-")
    return " ".join(normalized.split())


def is_supported_license(value: str | None) -> bool:
    """Return whether the provider label is explicitly reusable by policy."""

    return normalize_license_name(value) in SUPPORTED_LICENSES


def license_requires_author(value: str | None) -> bool:
    """Return whether attribution licenses require an identified author."""

    return normalize_license_name(value).startswith("cc by")


def license_requires_url(value: str | None) -> bool:
    """Return whether the accepted license must link to its legal terms."""

    return normalize_license_name(value).startswith("cc by")


def build_attribution_text(*, author: str | None, license_short_name: str) -> str:
    """Build plain-text attribution solely from provider metadata."""

    if not is_supported_license(license_short_name):
        raise ValueError("Unsupported image license")
    clean_author = " ".join((author or "").split())
    if license_requires_author(license_short_name) and not clean_author:
        raise ValueError("This license requires an identified author")
    parts = [part for part in (clean_author, license_short_name.strip()) if part]
    parts.append("Wikimedia Commons")
    return " / ".join(parts)
