from time import perf_counter
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import ToolNode

from app.core.logging import get_logger
from app.graph.state import TravelState
from app.llm.tools import get_tools

logger = get_logger(__name__)


class LoggingToolNode(ToolNode):
    """ToolNode variant that logs execution metadata without running tools manually."""

    def invoke(
        self,
        input: TravelState,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> Any:
        """Invoke LangGraph ToolNode with timing and tool-call logging."""

        started_at = perf_counter()
        tool_names = _get_latest_tool_names(input["messages"])
        logger.info(
            "tool_executor_node entered tool_count=%s tool_names=%s",
            len(tool_names),
            tool_names,
        )

        result = super().invoke(
            input,
            config=config,
            **kwargs,
        )

        duration = perf_counter() - started_at
        logger.info(
            "tool_executor_node exited tool_count=%s tool_names=%s duration=%.4fs",
            len(tool_names),
            tool_names,
            duration,
        )
        return result


def build_tool_executor_node() -> ToolNode:
    """Build the LangGraph ToolNode for executing application tools."""

    return LoggingToolNode(get_tools())


def _get_latest_tool_names(messages: list[BaseMessage]) -> list[str]:
    """Return tool names requested by the latest AI message."""

    if not messages:
        return []

    last_message = messages[-1]
    if not isinstance(last_message, AIMessage):
        return []

    return [
        tool_call["name"]
        for tool_call in last_message.tool_calls
    ]
