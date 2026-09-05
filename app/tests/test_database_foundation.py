import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import check_database_connection, get_db_session


def _postgres_available() -> bool:
    try:
        return asyncio.run(check_database_connection())
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_available(),
    reason="PostgreSQL is not available in this environment.",
)


def test_database_connection() -> None:
    assert asyncio.run(check_database_connection()) is True


def test_get_db_session_returns_async_session() -> None:
    async def run() -> None:
        async for session in get_db_session():
            assert isinstance(session, AsyncSession)
            break

    asyncio.run(run())


def test_query_execution() -> None:
    async def run() -> None:
        async for session in get_db_session():
            result = await session.execute(text("SELECT 1 AS value"))
            row = result.first()
            assert row is not None
            assert row.value == 1
            break

    asyncio.run(run())


def test_transaction_rollback() -> None:
    async def run() -> None:
        async for session in get_db_session():
            try:
                await session.execute(text("BEGIN"))
                await session.execute(text("SELECT 1"))
                await session.rollback()
            except Exception:
                pytest.fail("transaction rollback should not fail for a simple query")
            break

    asyncio.run(run())
