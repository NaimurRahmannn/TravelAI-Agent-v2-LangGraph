import asyncio
from pathlib import Path
from typing import Any

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from app.config import get_settings
from app.graph.nodes.agent import agent_node
from app.graph.nodes.approval import (
    approval_decision_router,
    approval_gate_node,
    approval_node,
)
from app.graph.nodes.clarification import clarification_node
from app.graph.nodes.extractor import extractor_node
from app.graph.nodes.itinerary import itinerary_node
from app.graph.nodes.memory_recall import memory_recall_node
from app.graph.nodes.memory_write import memory_write_node
from app.graph.nodes.planner import planner_node
from app.graph.nodes.responder import responder_node
from app.graph.nodes.tool_executor import build_tool_executor_node
from app.graph.routers.approval_router import approval_router
from app.graph.routers.clarification_router import clarification_router
from app.graph.routers.tool_router import tool_router
from app.graph.state import TravelState
from app.graph.subgraphs.research_graph import build_research_graph

async def _build_checkpointer() -> AsyncSqliteSaver:
    db_path = Path(get_settings().CHECKPOINTER_SQLITE_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(str(db_path))
    saver = AsyncSqliteSaver(conn)
    await saver.setup()  # idempotent - creates tables on first run only
    return saver


_graph: Any | None = None
_build_lock = asyncio.Lock()


async def get_graph() -> Any:
    global _graph

    if _graph is not None:
        return _graph

    async with _build_lock:
        if _graph is None:
            checkpointer = await _build_checkpointer()
            _graph = _build_graph(checkpointer)

    return _graph


def _build_graph(checkpointer: AsyncSqliteSaver) -> Any:
    """Build and compile the travel planning graph."""

    builder = StateGraph(TravelState)

    builder.add_node("planner", planner_node)
    builder.add_node("extractor", extractor_node)
    builder.add_node("clarification", clarification_node)
    builder.add_node("research", build_research_graph())
    builder.add_node("agent", agent_node)
    builder.add_node("approval_gate", approval_gate_node)
    builder.add_node("approval", approval_node)
    builder.add_node("tools", build_tool_executor_node())
    builder.add_node("itinerary", itinerary_node)
    builder.add_node("responder", responder_node)
    builder.add_node("memory_recall", memory_recall_node)
    builder.add_node("memory_write", memory_write_node)

    builder.add_edge(START, "planner")
    builder.add_edge("planner", "extractor")
    builder.add_conditional_edges(
        "extractor",
        clarification_router,
        {
            "clarification": "clarification",
            "responder": "research",
        },
    )
    builder.add_conditional_edges(
        "agent",
        tool_router,
        {
            "approval_gate": "approval_gate",
            "responder": "itinerary",       # normal completion -> format it
        },
    )
    builder.add_conditional_edges(
        "approval_gate",
        approval_router,
        {
            "approval": "approval",
            "tools": "tools",
        },
    )
    builder.add_conditional_edges(
        "approval",
        approval_decision_router,
        {
            "tools": "tools",
            "responder": "responder",       # rejection -> straight to responder, skip itinerary
        },
    )

    builder.add_edge("clarification", END)
    # Recall after trip extraction/research routing so clarification-only turns
    # stay lightweight, but before the agent reasons over a complete trip.
    builder.add_edge("research", "memory_recall")
    builder.add_edge("memory_recall", "agent")
    builder.add_edge("tools", "agent")
    builder.add_edge("itinerary", "responder")
    # Only final responses are written; clarification prompts skip Mem0 because
    # they rarely contain durable traveler facts and must remain a short-circuit.
    builder.add_edge("responder", "memory_write")
    builder.add_edge("memory_write", END)

    return builder.compile(checkpointer=checkpointer)