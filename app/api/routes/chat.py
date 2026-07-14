from fastapi import APIRouter

from app.services.graph_services import GraphService

router = APIRouter()

service = GraphService()


@router.post("/chat")
async def chat(
    message: str,
):
    return {
        "response": service.invoke(
            message,
        )
    }