from functools import lru_cache

from langchain_core.runnables import Runnable
from langchain_groq import ChatGroq

from app.config import get_settings
from app.llm.tools import get_tools


@lru_cache(maxsize=1)
def get_llm() -> ChatGroq:
    """Return the singleton Groq chat model instance."""

    settings = get_settings()
    return ChatGroq(
        api_key=settings.GROQ_API_KEY,
        model=settings.MODEL_NAME,
        temperature=settings.TEMPERATURE,
    )


@lru_cache(maxsize=1)
def get_tool_enabled_llm() -> Runnable:
    """Return the singleton Groq chat model bound to application tools."""

    return get_llm().bind_tools(get_tools())
