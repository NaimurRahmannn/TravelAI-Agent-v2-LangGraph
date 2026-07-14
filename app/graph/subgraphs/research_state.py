from typing import Annotated, TypedDict

from app.models import Trip


def merge_research_results(
    left: dict[str, str] | None,
    right: dict[str, str] | None,
) -> dict[str, str]:
    """Merge parallel research results without dropping sibling worker output."""

    merged: dict[str, str] = {}
    if left:
        merged.update(left)
    if right:
        merged.update(right)
    return merged


def merge_pending_tasks(
    left: list[str] | None,
    right: list[str] | None,
) -> list[str]:
    """Merge pending research tasks while preserving insertion order."""

    merged: list[str] = []
    for task in (left or []) + (right or []):
        if task not in merged:
            merged.append(task)
    return merged


class ResearchState(TypedDict):
    """Local state owned by the research subgraph."""

    trip: Trip | None
    research_results: Annotated[dict[str, str], merge_research_results]
    pending_tasks: Annotated[list[str], merge_pending_tasks]


class ResearchInput(TypedDict):
    """Input contract accepted by the research subgraph."""

    trip: Trip | None
    research_results: dict[str, str]


class ResearchOutput(TypedDict):
    """Output contract exposed from the research subgraph to the parent graph."""

    research_results: dict[str, str]
