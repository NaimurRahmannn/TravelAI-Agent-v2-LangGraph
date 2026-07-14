from typing import Any

from fastapi import HTTPException
from langchain_core.messages import HumanMessage

from app.core.logging import get_logger
from app.graph.builder import build_graph
from app.schemas.api import ChatRequest, ChatResponse

logger = get_logger(__name__)


class GraphService:
    """Application service responsible for invoking the travel graph."""

    def __init__(self) -> None:
        """Compile the travel graph once for this service instance."""

        self._graph = build_graph()

    def invoke(self, request: ChatRequest) -> ChatResponse:
        """Invoke the travel graph and return a typed chat response."""

        try:
            config = self._build_config(request)
            result = self._graph.invoke(
                {
                    "messages": [
                        HumanMessage(content=request.message),
                    ],
                },
                config=config,
            )
            return ChatResponse(
                response=result["response"],
                trip=result.get("trip"),
            )
        except Exception as exc:
            logger.exception("Graph invocation failed")
            raise HTTPException(
                status_code=500,
                detail="Failed to process chat request.",
            ) from exc

    @staticmethod
    def _build_config(request: ChatRequest) -> dict[str, Any] | None:
        if request.thread_id is None:
            return None

        return {
            "configurable": {
                "thread_id": request.thread_id,
            },
        }
