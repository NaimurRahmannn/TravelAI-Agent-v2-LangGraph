import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.approval import router as approval_router
from app.api.routes.chat import router as chat_router
from app.api.routes.health import router as health_router
from app.api.routes.stream import router as stream_router

app = FastAPI(
    title="Travel AI Agent",
    version="1.0.0",
)


def _get_allowed_origins() -> list[str]:
    """Return frontend origins allowed to call the API."""

    configured_origins = os.getenv("CORS_ALLOWED_ORIGINS")
    if configured_origins:
        return [
            origin.strip()
            for origin in configured_origins.split(",")
            if origin.strip()
        ]

    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(chat_router)
app.include_router(stream_router)
app.include_router(approval_router)


@app.get("/")
async def root() -> dict[str, str]:
    """Return the API root message."""

    return {
        "message": "Travel AI Agent"
    }
