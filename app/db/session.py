from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.core.logging import get_logger
from app.db.base import Base

logger = get_logger(__name__)


def _database_url() -> str:
    """Return the active database URL, preferring the test database for tests."""

    settings = get_settings()
    return settings.TEST_DATABASE_URL or settings.DATABASE_URL


engine = create_async_engine(
    _database_url(),
    echo=get_settings().DATABASE_ECHO,
    pool_size=get_settings().DB_POOL_SIZE,
    max_overflow=get_settings().DB_MAX_OVERFLOW,
    pool_timeout=get_settings().DB_POOL_TIMEOUT,
    pool_recycle=get_settings().DB_POOL_RECYCLE,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session for request-scoped work."""

    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def check_database_connection() -> bool:
    """Verify the database is reachable."""

    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.exception("Database connectivity check failed.")
        return False


async def dispose_db_engine() -> None:
    """Dispose the application-wide engine on shutdown."""

    await engine.dispose()


def get_engine() -> Any:
    """Return the application engine for migration and startup wiring."""

    return engine


__all__ = [
    "Base",
    "async_session_factory",
    "check_database_connection",
    "dispose_db_engine",
    "get_db_session",
    "get_engine",
]
