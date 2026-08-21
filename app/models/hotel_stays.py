import hashlib
import re
import unicodedata
from datetime import date


def build_hotel_stay_key(city: str | None, check_in: date, check_out: date) -> str:
    """Build an opaque deterministic key from normalized city and stay dates."""

    decomposed = unicodedata.normalize("NFKD", city or "").casefold()
    without_marks = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    normalized_city = " ".join(re.findall(r"[a-z0-9]+", without_marks))
    payload = f"{normalized_city}|{check_in.isoformat()}|{check_out.isoformat()}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"stay_{digest}"
