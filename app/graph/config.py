from app.config import get_settings

settings = get_settings()

GROQ_API_KEY = settings.GROQ_API_KEY
MODEL_NAME = settings.MODEL_NAME
TEMPERATURE = settings.TEMPERATURE
