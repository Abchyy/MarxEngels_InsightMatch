"""Feedback contract endpoint."""

from fastapi import APIRouter

from marx_engels.contracts import ErrorResponse, FeedbackRequest, FeedbackResponse
from marx_engels.errors import DomainError

router = APIRouter(tags=["feedback"])


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    responses={501: {"model": ErrorResponse}},
    operation_id="submit_feedback",
)
async def submit_feedback(payload: FeedbackRequest) -> FeedbackResponse:
    del payload
    raise DomainError(
        "STORAGE_NOT_CONFIGURED",
        "Feedback persistence is defined but not implemented in the baseline.",
    )
