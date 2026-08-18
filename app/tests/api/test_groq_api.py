from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import get_settings
from app.llm import get_gemini_llm, get_groq_llm


def test_task_models_use_their_configured_providers():
    """Create both role-specific clients without making live API calls."""

    settings = get_settings()
    groq_llm = get_groq_llm()
    gemini_llm = get_gemini_llm()

    assert isinstance(groq_llm, ChatGroq)
    assert groq_llm.model_name == settings.GROQ_MODEL_NAME
    assert isinstance(gemini_llm, ChatGoogleGenerativeAI)
    assert gemini_llm.model == settings.GEMINI_MODEL_NAME
