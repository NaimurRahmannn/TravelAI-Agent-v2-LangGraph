from pydantic import BaseModel


class ApprovalRequest(BaseModel):
    """Request body used to resume an interrupted approval workflow."""

    thread_id: str
    approved: bool


class ApprovalResponse(BaseModel):
    """Response returned after resuming an approval workflow."""

    status: str
    thread_id: str
