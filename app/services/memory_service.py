from __future__ import annotations

from functools import lru_cache
from typing import Any

from mem0 import Memory

from app.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class MemoryService:
    """Thin wrapper around a Mem0 `Memory` instance for traveler facts."""

    def __init__(self) -> None:
        settings = get_settings()
        self._memory = Memory.from_config(self._build_config(settings))

    @staticmethod
    def _build_config(settings: Any) -> dict[str, Any]:
        """Build the Mem0 config dict from application settings."""

        return {
            "vector_store": {
                "provider": settings.MEM0_VECTOR_STORE_PROVIDER,
                "config": {
                    "collection_name": "travel_ai_memories",
                    "path": settings.MEM0_VECTOR_STORE_PATH,
                    "embedding_model_dims": settings.MEM0_EMBEDDING_DIMS,
                },
            },
            "embedder": {
                "provider": settings.MEM0_EMBEDDER_PROVIDER,
                "config": {
                    "model": settings.MEM0_EMBEDDER_MODEL,
                    "embedding_dims": settings.MEM0_EMBEDDING_DIMS,
                },
            },
            "llm": {
                "provider": "groq",
                "config": {
                    "model": settings.MODEL_NAME,
                    "api_key": settings.GROQ_API_KEY,
                    "temperature": settings.TEMPERATURE,
                },
            },
        }

    def recall(self, query: str, user_id: str, limit: int = 5) -> list[str]:
        """Return up to `limit` relevant memory strings for a traveler.

        Never raises: a Mem0/vector-store hiccup should degrade to "no
        memories" rather than take down the whole graph turn.
        """

        if not query or not user_id:
            return []

        try:
            result = self._memory.search(
                query,
                filters={"user_id": user_id},
                top_k=limit,
            )
        except Exception:
            logger.exception("memory recall failed user_id=%s", user_id)
            return []

        return [
            item["memory"] for item in result.get("results", []) if item.get("memory")
        ]

    def remember(
        self,
        messages: list[dict[str, str]],
        user_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Extract and store durable facts from a conversation turn.

        Fire-and-forget from the graph's point of view: failures are
        logged, not raised, so a Mem0 outage never breaks a chat turn.
        """

        if not messages or not user_id:
            return

        try:
            self._memory.add(
                messages,
                user_id=user_id,
                metadata=metadata,
            )
        except Exception:
            logger.exception("memory write failed user_id=%s", user_id)


@lru_cache(maxsize=1)
def get_memory_service() -> MemoryService:
    """Return the process-wide singleton MemoryService instance."""

    return MemoryService()
