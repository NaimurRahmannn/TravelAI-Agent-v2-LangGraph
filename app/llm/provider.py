from functools import lru_cache

from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq

from app.config import get_settings
from app.llm.tools import get_tools


@lru_cache(maxsize=1)
def get_groq_llm() -> ChatGroq:
    """Return Groq for extraction and clarification tasks."""

    settings = get_settings()
    return ChatGroq(
        api_key=settings.GROQ_API_KEY,
        model=settings.GROQ_MODEL_NAME,
        temperature=settings.TEMPERATURE,
        timeout=30,
        max_retries=2,
    )


@lru_cache(maxsize=1)
def get_gemini_llm() -> ChatGoogleGenerativeAI:
    """Return Gemini for tool reasoning and final answer generation."""

    settings = get_settings()
    return ChatGoogleGenerativeAI(
        api_key=settings.GEMINI_API_KEY,
        model=settings.GEMINI_MODEL_NAME,
        temperature=settings.TEMPERATURE,
        timeout=30,
        max_retries=2,
    )


@lru_cache(maxsize=1)
def get_tool_enabled_llm() -> Runnable:
    """Return the singleton Gemini chat model bound to application tools."""

    return get_gemini_llm().bind_tools(get_tools())
