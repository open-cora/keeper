"""HTTP door for reading an inquiry.

`GET /inquiries/{inquiry_id}`. Returns who asked, what they wanted to know,
what a thinker concluded if one has, and how much of the execution that
thinker had in front of it.

`status` is here where the proposal next door has none, and the difference
is that this record has three states rather than two. A proposal is open or
taken and one nullable field says which; an inquiry can be open, claimed or
answered, and no single field carries that.

`conclusion`, `observed_step_count` and `execution_ended` are null until an
answer lands, and after that none of them is. The three arrive together
from one event.

`observed_step_count` beside `execution_step_count` is the observation
boundary, and reading them as a pair is the point. The same conclusion
means something different at two of six than it does at six of six, and
this is the only place that difference survives: by the time anybody reads
this the execution has moved on.

The state is folded from the stream on every call. An inquiry is one row to
three, so a summary table would be machinery maintained ahead of a need.
That changes for the question which names no inquiry, which is what the
listing serves.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from keeper.counsel.aggregates.inquiry import InquiryConclusion, InquiryStatus
from keeper.counsel.features.get_inquiry.handler import Handler
from keeper.counsel.features.get_inquiry.query import GetInquiry
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class GetInquiryResponse(BaseModel):
    """An inquiry as this system currently holds it."""

    inquiry_id: UUID
    actor_id: UUID
    execution_id: UUID
    objective: str
    execution_step_count: int
    status: InquiryStatus
    conclusion: InquiryConclusion | None
    observed_step_count: int | None
    execution_ended: bool | None
    proposal_id: UUID | None


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.counsel.get_inquiry
    return handler


router = APIRouter(tags=["counsel"])


@router.get(
    "/inquiries/{inquiry_id}",
    response_model=GetInquiryResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read inquiries.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No inquiry has that id.",
        },
    },
    summary="Read an inquiry",
)
async def get_inquiry(
    inquiry_id: UUID,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> GetInquiryResponse:
    inquiry = await handler(
        GetInquiry(inquiry_id=inquiry_id),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    return GetInquiryResponse(
        inquiry_id=inquiry.id,
        actor_id=inquiry.actor_id,
        execution_id=inquiry.execution_id,
        objective=inquiry.objective.value,
        execution_step_count=inquiry.execution_step_count,
        status=inquiry.status,
        conclusion=inquiry.conclusion,
        observed_step_count=inquiry.observed_step_count,
        execution_ended=inquiry.execution_ended,
        proposal_id=inquiry.proposal_id,
    )
