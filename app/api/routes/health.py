from fastapi import APIRouter

from app.db import check_database_connection

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str | bool]:
    """Return the API health status and the database connectivity state."""

    return {
        "status": "ok",
        "database": await check_database_connection(),
    }
