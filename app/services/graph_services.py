from uuid import uuid4

from fastapi import HTTPException
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from app.core.logging import get_logger
from app.graph.builder import get_graph
from app.schemas.api import ChatRequest, ChatResponse

logger = get_logger(__name__)


class GraphService:
    """Application service responsible for invoking the travel graph."""

    def __init__(self) -> None:
        """Compile the travel graph once for this service instance."""

        self._graph = get_graph()

    def invoke(self, request: ChatRequest) -> ChatResponse:
        """Invoke the travel graph and return a typed chat response."""

        thread_id = request.thread_id or str(uuid4())
        config = self._build_config(thread_id)

        try:
            logger.info("checkpoint load thread_id=%s", thread_id)
            self._graph.get_state(config)

            logger.info("graph invocation started thread_id=%s", thread_id)
            result = self._graph.invoke(
                {
                    "messages": [
                        HumanMessage(content=request.message),
                    ],
                },
                config=config,
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

    @staticmethod
    def _build_config(thread_id: str) -> RunnableConfig:
        """Build the LangGraph runnable config for a conversation thread."""

        return {
            "configurable": {
                "thread_id": thread_id,
            },
        }
