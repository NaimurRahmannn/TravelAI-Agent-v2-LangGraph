from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    GEMINI_API_KEY: str = Field(
        validation_alias=AliasChoices("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    )
    GROQ_API_KEY: str
    GEMINI_MODEL_NAME: str = "gemini-2.5-flash-lite"
    GROQ_MODEL_NAME: str = Field(
        default="openai/gpt-oss-20b",
        validation_alias=AliasChoices("GROQ_MODEL_NAME", "MODEL_NAME"),
    )
    GEOAPIFY_API_KEY: str | None = None
    GEOAPIFY_MAPS_API_KEY: str | None = None
    PEXELS_API_KEY: str | None = None
    OPENWEATHER_API_KEY: str | None = None
    LITEAPI_API_KEY: str | None = None
    TEMPERATURE: float = 0.0
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/travelai"
    TEST_DATABASE_URL: str | None = None
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    DATABASE_ECHO: bool = False
    MEM0_VECTOR_STORE_PROVIDER: str = "qdrant"
    MEM0_VECTOR_STORE_PATH: str = "app/.mem0/qdrant"
    MEM0_QDRANT_URL: str | None = None
    MEM0_QDRANT_API_KEY: str | None = None
    MEM0_EMBEDDER_PROVIDER: str = "fastembed"
    MEM0_EMBEDDER_MODEL: str = "BAAI/bge-small-en-v1.5"
    MEM0_EMBEDDING_DIMS: int = 384
    CHECKPOINTER_SQLITE_PATH: str = "app/.data/checkpoints.sqlite"

    model_config = SettingsConfigDict(
        env_file="app/.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings instance."""

    return Settings()
