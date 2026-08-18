from collections.abc import Mapping, Sequence
from typing import Any


def message_content_to_text(content: Any) -> str:
    """Convert plain or block-based LangChain content into clean text."""

    if isinstance(content, str):
        return content

    if isinstance(content, Mapping):
        text = content.get("text")
        return text if isinstance(text, str) else ""

    if isinstance(content, Sequence) and not isinstance(content, (bytes, bytearray)):
        text_parts = [message_content_to_text(block) for block in content]
        return "\n".join(part for part in text_parts if part)

    return ""
