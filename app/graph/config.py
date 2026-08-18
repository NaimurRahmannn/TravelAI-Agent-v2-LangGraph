from app.config import get_settings

settings = get_settings()

GEMINI_API_KEY = settings.GEMINI_API_KEY
GROQ_API_KEY = settings.GROQ_API_KEY
GROQ_MODEL_NAME = settings.GROQ_MODEL_NAME
GEMINI_MODEL_NAME = settings.GEMINI_MODEL_NAME
TEMPERATURE = settings.TEMPERATURE
