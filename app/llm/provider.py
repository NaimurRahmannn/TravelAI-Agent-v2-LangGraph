from langchain_groq import ChatGroq

from app.config import (
    GROQ_API_KEY,
    MODEL_NAME,
    TEMPERATURE,
)


def get_llm() -> ChatGroq:
    """
    Return the application's default chat model.

    Every graph node should obtain its LLM through this
    function instead of instantiating ChatGroq directly.
    """

    return ChatGroq(
        api_key=GROQ_API_KEY,
        model=MODEL_NAME,
        temperature=TEMPERATURE,
    )