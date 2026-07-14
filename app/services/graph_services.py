from collections.abc import AsyncIterator, Iterator
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
from app.schemas.api import ChatRequest, ChatResponse, StreamMode

logger = get_logger(__name__)


class GraphService:
    """Application service responsible for invoking and streaming the graph."""

    def __init__(self) -> None:
        """Load the singleton compiled graph with its MemorySaver checkpointer."""

        self._graph = get_graph()

    def invoke(self, request: ChatRequest) -> ChatResponse:
        """Invoke the travel graph synchronously and return a typed response."""

        thread_id = self.resolve_thread_id(request.thread_id)
        config = self.build_config(thread_id)

        try:
            logger.info("checkpoint load thread_id=%s", thread_id)
            self._graph.get_state(config)
            logger.info("graph invocation started thread_id=%s", thread_id)

            result = self._graph.invoke(
                self.build_input(request),
                config=config,
            )
            if "__interrupt__" in result:
                return ChatResponse(
                    response="Approval required before continuing.",
                    thread_id=thread_id,
                )

            logger.info("checkpoint save thread_id=%s", thread_id)
            self._graph.get_state(config)
            logger.info("graph invocation finished thread_id=%s", thread_id)
            return ChatResponse(
                response=result["response"],
                thread_id=thread_id,
            )
        except Exception as exc:
            logger.exception("Graph invocation failed thread_id=%s", thread_id)
            raise HTTPException(
                status_code=500,
                detail="Failed to process chat request.",
            ) from exc

    async def ainvoke(self, request: ChatRequest) -> ChatResponse:
        """Invoke the travel graph asynchronously and return a typed response."""

        thread_id = self.resolve_thread_id(request.thread_id)
        config = self.build_config(thread_id)

        try:
            logger.info("checkpoint load thread_id=%s", thread_id)
            await self._graph.aget_state(config)
            logger.info("graph async invocation started thread_id=%s", thread_id)

            result = await self._graph.ainvoke(
                self.build_input(request),
                config=config,
            )
            if "__interrupt__" in result:
                return ChatResponse(
                    response="Approval required before continuing.",
                    thread_id=thread_id,
                )

            logger.info("checkpoint save thread_id=%s", thread_id)
            await self._graph.aget_state(config)
            logger.info("graph async invocation finished thread_id=%s", thread_id)
            return ChatResponse(
                response=result["response"],
                thread_id=thread_id,
            )
        except Exception as exc:
            logger.exception("Async graph invocation failed thread_id=%s", thread_id)
            raise HTTPException(
                status_code=500,
                detail="Failed to process chat request.",
            ) from exc

    def resume(self, request: ApprovalRequest) -> ApprovalResponse:
        """Resume an interrupted graph after a human approval decision."""

        started_at = perf_counter()
        config = self.build_config(request.thread_id)

        try:
            logger.info(
                "interrupt resumed thread_id=%s approved=%s",
                request.thread_id,
                request.approved,
            )
            self._graph.invoke(
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
            logger.exception("Graph resume failed thread_id=%s", request.thread_id)
            raise HTTPException(
                status_code=500,
                detail="Failed to resume chat request.",
            ) from exc

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
            await self._graph.ainvoke(
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

    def stream(
        self,
        request: ChatRequest,
        stream_mode: StreamMode | None = None,
    ) -> Iterator[Any]:
        """Stream graph output synchronously using LangGraph native streaming."""

        thread_id = self.resolve_thread_id(request.thread_id)
        mode = stream_mode or request.stream_mode
        config = self.build_config(thread_id)
        started_at = perf_counter()
        logger.info("stream start thread_id=%s stream_mode=%s", thread_id, mode)

        try:
            for chunk in self._graph.stream(
                self.build_input(request),
                config=config,
                stream_mode=mode,
            ):
                yield chunk
        finally:
            duration = perf_counter() - started_at
            logger.info(
                "stream end thread_id=%s stream_mode=%s duration=%.4fs",
                thread_id,
                mode,
                duration,
            )

    async def astream(
        self,
        request: ChatRequest,
        stream_mode: StreamMode | None = None,
    ) -> AsyncIterator[Any]:
        """Stream graph output asynchronously using LangGraph native streaming."""

        thread_id = self.resolve_thread_id(request.thread_id)
        mode = stream_mode or request.stream_mode
        config = self.build_config(thread_id)
        started_at = perf_counter()
        logger.info("astream start thread_id=%s stream_mode=%s", thread_id, mode)

        try:
            async for chunk in self._graph.astream(
                self.build_input(request),
                config=config,
                stream_mode=mode,
            ):
                yield chunk
        finally:
            duration = perf_counter() - started_at
            logger.info(
                "astream end thread_id=%s stream_mode=%s duration=%.4fs",
                thread_id,
                mode,
                duration,
            )

    async def astream_events(
        self,
        request: ChatRequest,
        stream_mode: StreamMode | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream graph lifecycle and token events using LangGraph event streaming."""

        thread_id = self.resolve_thread_id(request.thread_id)
        mode = stream_mode or request.stream_mode
        config = self.build_config(thread_id)
        started_at = perf_counter()
        logger.info("astream_events start thread_id=%s stream_mode=%s", thread_id, mode)

        try:
            async for event in self._graph.astream_events(
                self.build_input(request),
                config=config,
                version="v2",
            ):
                event["thread_id"] = thread_id
                event["stream_mode"] = mode
                yield event
        finally:
            duration = perf_counter() - started_at
            logger.info(
                "astream_events end thread_id=%s stream_mode=%s duration=%.4fs",
                thread_id,
                mode,
                duration,
            )

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
    def build_input(request: ChatRequest) -> dict[str, list[HumanMessage]]:
        """Build the graph input from an API chat request."""

        return {
            "messages": [
                HumanMessage(content=request.message),
            ],
        }
