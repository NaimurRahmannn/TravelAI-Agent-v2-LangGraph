from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from app.core.logging import get_logger
from app.graph.builder import get_graph
from app.schemas.approval import ApprovalRequest, ApprovalResponse
from app.schemas.api import ChatRequest, ChatResponse

logger = get_logger(__name__)


class GraphService:
    """Application service responsible for invoking the graph."""

    def __init__(self) -> None:
        """Construct the service. The compiled graph is fetched lazily.

        get_graph() is async (AsyncSqliteSaver needs a running event loop
        to open its connection), so it can't be resolved here in a plain
        __init__. Each call below awaits self._get_graph() instead, which
        builds the graph once on first use and reuses it after that.
        """

    @staticmethod
    async def _get_graph() -> Any:
        """Return the shared compiled graph, building it on first use."""

        return await get_graph()

    def invoke(self, request: ChatRequest) -> ChatResponse:
        """Synchronous invocation is not supported.

        The graph is compiled with AsyncSqliteSaver, which only implements
        the async checkpoint API (mirroring the original bug in reverse:
        AsyncSqliteSaver.get_state()/.invoke() raise, only the a-prefixed
        methods work). Nothing in this app's routes calls this method; use
        ainvoke instead.
        """

        raise HTTPException(
            status_code=501,
            detail="Synchronous graph execution isn't supported with the "
            "async SQLite checkpointer. Use ainvoke instead.",
        )

    async def ainvoke(self, request: ChatRequest) -> ChatResponse:
        """Invoke the travel graph asynchronously and return a typed response."""

        thread_id = self.resolve_thread_id(request.thread_id)
        config = self.build_config(thread_id)

        try:
            graph = await self._get_graph()
            logger.info("checkpoint load thread_id=%s", thread_id)
            await graph.aget_state(config)
            logger.info("graph async invocation started thread_id=%s", thread_id)

            result = await graph.ainvoke(
                self.build_input(request),
                config=config,
            )
            if "__interrupt__" in result:
                return ChatResponse(
                    response="Approval required before continuing.",
                    thread_id=thread_id,
                    itinerary=None,
                    missing_fields=[],
                )

            logger.info("checkpoint save thread_id=%s", thread_id)
            await graph.aget_state(config)
            logger.info("graph async invocation finished thread_id=%s", thread_id)
            return ChatResponse(
                response=result.get("response", ""),
                thread_id=thread_id,
                itinerary=result.get("itinerary"),
                missing_fields=result.get("missing_fields", []),
            )
        except Exception as exc:
            logger.exception("Async graph invocation failed thread_id=%s", thread_id)
            raise HTTPException(
                status_code=500,
                detail="Failed to process chat request.",
            ) from exc

    def resume(self, request: ApprovalRequest) -> ApprovalResponse:
        """Synchronous resume is not supported; see invoke() docstring."""

        raise HTTPException(
            status_code=501,
            detail="Synchronous graph execution isn't supported with the "
            "async SQLite checkpointer. Use aresume instead.",
        )

    async def aresume(self, request: ApprovalRequest) -> ApprovalResponse:
        """Resume an interrupted graph asynchronously after human approval."""

        started_at = perf_counter()
        config = self.build_config(request.thread_id)

        try:
            logger.info(
                "interrupt resumed thread_id=%s approved=%s",
                request.thread_id,
                request.approved,
            )
            graph = await self._get_graph()
            await graph.ainvoke(
                Command(
                    resume={
                        "approved": request.approved,
                    }
                ),
                config=config,
            )
            duration = perf_counter() - started_at
            logger.info(
                "resume duration thread_id=%s approved=%s duration=%.4fs",
                request.thread_id,
                request.approved,
                duration,
            )
            return ApprovalResponse(
                status="accepted" if request.approved else "rejected",
                thread_id=request.thread_id,
            )
        except Exception as exc:
            logger.exception("Async graph resume failed thread_id=%s", request.thread_id)
            raise HTTPException(
                status_code=500,
                detail="Failed to resume chat request.",
            ) from exc

    @staticmethod
    def resolve_thread_id(thread_id: str | None) -> str:
        """Return the provided thread id or generate a new UUID."""

        return thread_id or str(uuid4())

    @staticmethod
    def build_config(thread_id: str) -> RunnableConfig:
        """Build the LangGraph runnable config for a conversation thread."""

        return {
            "configurable": {
                "thread_id": thread_id,
            },
        }

    @staticmethod
    def build_input(request: ChatRequest) -> dict[str, Any]:
        """Build the graph input from an API chat request."""

        return {
            "messages": [
                HumanMessage(content=request.message),
            ],
            "user_id": request.user_id,
            "selected_start_date": request.start_date,
            "selected_end_date": request.end_date,
            "guest_nationality_country_code": (
                request.guest_nationality_country_code
            ),
        }
