from functools import lru_cache

from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import get_settings
from app.llm.tools import get_tools


@lru_cache(maxsize=1)
def get_llm() -> ChatGoogleGenerativeAI:
    """Return the singleton Gemini chat model instance."""

    settings = get_settings()
    return ChatGoogleGenerativeAI(
        api_key=settings.GEMINI_API_KEY,
        model=settings.MODEL_NAME,
        temperature=settings.TEMPERATURE,
        timeout=30,
        max_retries=2,
    )


@lru_cache(maxsize=1)
def get_tool_enabled_llm() -> Runnable:
    """Return the singleton Gemini chat model bound to application tools."""

    return get_llm().bind_tools(get_tools())
