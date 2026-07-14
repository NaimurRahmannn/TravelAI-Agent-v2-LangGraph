from collections.abc import AsyncIterator
from datetime import UTC, datetime
import json
from time import perf_counter
from typing import Any

from app.core.logging import get_logger
from app.schemas.api import ChatRequest
from app.services.graph_services import GraphService

logger = get_logger(__name__)


class StreamService:
    """Service that converts LangGraph streams into FastAPI SSE events."""

    def __init__(self, graph_service: GraphService | None = None) -> None:
        """Initialize the stream service with the shared graph service."""

        self._graph_service = graph_service or GraphService()

    async def chat_stream(self, request: ChatRequest) -> AsyncIterator[str]:
        """Yield server-sent events for a chat request."""

        thread_id = self._graph_service.resolve_thread_id(request.thread_id)
        stream_request = request.model_copy(
            update={
                "thread_id": thread_id,
            }
        )
        started_at = perf_counter()
        logger.info(
            "stream start thread_id=%s stream_mode=%s",
            thread_id,
            stream_request.stream_mode,
        )

        try:
            yield self._format_sse(
                {
                    "event_type": "stream_start",
                    "node": "StreamService",
                    "content": "Stream started",
                    "thread_id": thread_id,
                    "timestamp": self._timestamp(),
                }
            )

            async for event in self._graph_service.astream_events(stream_request):
                normalized_event = self._normalize_event(event, thread_id)
                if normalized_event is not None:
                    yield self._format_sse(normalized_event)

            yield self._format_sse(
                {
                    "event_type": "stream_end",
                    "node": "StreamService",
                    "content": "Stream finished",
                    "thread_id": thread_id,
                    "timestamp": self._timestamp(),
                }
            )
        except Exception as exc:
            logger.exception("stream error thread_id=%s", thread_id)
            yield self._format_sse(
                {
                    "event_type": "stream_error",
                    "node": "StreamService",
                    "content": str(exc),
                    "thread_id": thread_id,
                    "timestamp": self._timestamp(),
                }
            )
        finally:
            duration = perf_counter() - started_at
            logger.info(
                "stream end thread_id=%s stream_mode=%s duration=%.4fs",
                thread_id,
                stream_request.stream_mode,
                duration,
            )

    def _normalize_event(
        self,
        event: dict[str, Any],
        thread_id: str,
    ) -> dict[str, str] | None:
        """Normalize a LangGraph event into the public SSE payload shape."""

        event_type = str(event.get("event", "unknown"))
        metadata = event.get("metadata") or {}
        node = str(
            metadata.get("langgraph_node")
            or metadata.get("langgraph_path")
            or event.get("name")
            or "graph"
        )
        content = self._extract_content(event)

        if content == "" and event_type.endswith("_stream"):
            return None

        return {
            "event_type": event_type,
            "node": node,
            "content": content,
            "thread_id": thread_id,
            "timestamp": self._timestamp(),
        }

    def _extract_content(self, event: dict[str, Any]) -> str:
        """Extract human-readable content from a LangGraph stream event."""

        data = event.get("data") or {}
        event_type = str(event.get("event", ""))

        if event_type == "on_chat_model_stream":
            chunk = data.get("chunk")
            return self._stringify(getattr(chunk, "content", chunk))

        if event_type == "on_tool_start":
            return self._stringify(data.get("input", "Tool started"))

        if event_type == "on_tool_end":
            return self._stringify(data.get("output", "Tool finished"))

        if event_type.endswith("_start"):
            return self._stringify(data.get("input", "Started"))

        if event_type.endswith("_end"):
            return self._stringify(data.get("output", "Finished"))

        if "chunk" in data:
            chunk = data["chunk"]
            return self._stringify(getattr(chunk, "content", chunk))

        return self._stringify(data)

    def _format_sse(self, payload: dict[str, str]) -> str:
        """Format a normalized payload as a server-sent event."""

        event_type = payload["event_type"]
        data = json.dumps(
            payload,
            ensure_ascii=True,
        )
        return f"event: {event_type}\ndata: {data}\n\n"

    def _stringify(self, value: Any) -> str:
        """Convert stream event content into a JSON-safe string."""

        if value is None:
            return ""

        if isinstance(value, str):
            return value

        if hasattr(value, "model_dump"):
            return json.dumps(
                value.model_dump(),
                ensure_ascii=True,
                default=str,
            )

        return json.dumps(
            value,
            ensure_ascii=True,
            default=str,
        )

    @staticmethod
    def _timestamp() -> str:
        """Return the current UTC timestamp for an SSE event."""

        return datetime.now(UTC).isoformat()
