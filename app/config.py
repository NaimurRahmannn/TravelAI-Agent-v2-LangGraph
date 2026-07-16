from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    GROQ_API_KEY: str
    MODEL_NAME: str = "llama-3.3-70b-versatile"
    TEMPERATURE: float = 0.0
    MEM0_VECTOR_STORE_PROVIDER: str = "qdrant"
    MEM0_VECTOR_STORE_PATH: str = "app/.mem0/qdrant"
    # Groq is supported by Mem0 as an LLM provider, but not as an embedder.
    # Hugging Face lets local development run without a second hosted API key.
    MEM0_EMBEDDER_PROVIDER: str = "huggingface"
    MEM0_EMBEDDER_MODEL: str = "multi-qa-MiniLM-L6-cos-v1"
    MEM0_EMBEDDING_DIMS: int = 384

    model_config = SettingsConfigDict(
        env_file="app/.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings instance."""

    return Settings()
