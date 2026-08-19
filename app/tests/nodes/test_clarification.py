from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.graph.nodes import clarification
from app.graph.nodes.clarification import (
    DATE_SELECTION_RESPONSE,
    clarification_node,
)


def test_dates_are_prioritized_as_a_dedicated_clarification(monkeypatch):
    def fail_if_called():
        raise AssertionError("Date selection must not call the clarification LLM")

    monkeypatch.setattr(clarification, "get_groq_llm", fail_if_called)
    missing_fields = ["budget", "dates", "origin", "travelers"]

    result = clarification_node(
        {"missing_fields": missing_fields},
        config={},
    )

    assert result == {
        "response": DATE_SELECTION_RESPONSE,
        "missing_fields": missing_fields,
    }


def test_non_date_clarification_keeps_existing_llm_flow(monkeypatch):
    monkeypatch.setattr(
        clarification,
        "get_groq_llm",
        lambda: RunnableLambda(lambda _: AIMessage(content="What is your budget?")),
    )

    result = clarification_node(
        {"missing_fields": ["budget"]},
        config={},
    )

    assert result == {
        "response": "What is your budget?",
        "missing_fields": ["budget"],
    }
