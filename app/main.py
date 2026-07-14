from fastapi import FastAPI

from app.api.routes.health import router as health_router

app = FastAPI(
    title="Travel AI Agent",
    version="1.0.0",
)

app.include_router(health_router)


@app.get("/")
async def root():
    return {
        "message": "Travel AI Agent"
    }