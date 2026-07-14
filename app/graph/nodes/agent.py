from time import perf_counter

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from app.core.logging import get_logger
from app.graph.state import TravelState
from app.llm import get_tool_enabled_llm

logger = get_logger(__name__)


def agent_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, list[AIMessage]]:
    """Reason over the conversation and decide whether tools are needed."""

    started_at = perf_counter()
    logger.info(
        "agent_node entered tool_count=%s tool_names=%s",
        0,
        [],
    )

    llm = get_tool_enabled_llm()
    messages = _build_agent_messages(state)
    response = llm.invoke(
        messages,
        config=config,
    )

    tool_names = [
        tool_call["name"]
        for tool_call in response.tool_calls
    ]
    duration = perf_counter() - started_at
    logger.info(
        "agent_node exited tool_count=%s tool_names=%s duration=%.4fs",
        len(tool_names),
        tool_names,
        duration,
    )

    return {
        "messages": [
            response,
        ],
    }


def _build_agent_messages(state: TravelState) -> list[BaseMessage]:
    """Return message history enriched with merged research context."""

    messages: list[BaseMessage] = list(state["messages"])
    research_summary = state.get("research_results", {}).get("summary")

    if not research_summary:
        return messages

    return [
        SystemMessage(
            content=(
                "Use this destination research when helpful. Do not mention "
                "that it came from an internal research subgraph.\n\n"
                f"{research_summary}"
            )
        ),
        *messages,
    ]
