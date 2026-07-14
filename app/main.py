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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
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
