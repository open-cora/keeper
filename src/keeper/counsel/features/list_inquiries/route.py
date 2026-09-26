"""HTTP door for finding inquiries.

`GET /inquiries`, newest first, one page at a time.

`status` is the filter, and `Claimed` is the one worth knowing about: it
narrows to questions something said it was thinking about. Nothing expires
a claim, so a row that has sat there since yesterday is how an abandoned
thinker becomes visible. That is deliberately a view rather than a rule,
since a claim that timed itself out would release work this system cannot
prove was abandoned.

The objective rides on every row, unlike the proposal listing's
parameters. It is bounded, and it is bounded partly so it can: a list of
questions with the questions taken out is a list of identifiers.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel

from keeper.counsel.aggregates.inquiry import InquiryConclusion, InquiryStatus
from keeper.counsel.features.list_inquiries.handler import Handler
from keeper.counsel.features.list_inquiries.query import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ListInquiries,
)
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class InquirySummaryResponse(BaseModel):
    """An inquiry as a list shows it."""

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
    created_at: datetime
    claimed_at: datetime | None
    answered_at: datetime | None


class ListInquiriesResponse(BaseModel):
    """One page of inquiries, and how to ask for the next."""

    items: list[InquirySummaryResponse]
    next_cursor: str | None


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.counsel.list_inquiries
    return handler


router = APIRouter(tags=["counsel"])


@router.get(
    "/inquiries",
    response_model=ListInquiriesResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read inquiries.",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "The cursor is not one this system issued.",
        },
    },
    summary="Find inquiries",
)
async def get_inquiries(
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    inquiry_status: Annotated[
        InquiryStatus | None,
        Query(
            alias="status",
            description="Open for questions nothing has taken up, Claimed for ones "
            "something is thinking about, Answered for ones a thinker came back to.",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query(description="Continue a previous page.")] = None,
) -> ListInquiriesResponse:
    page = await handler(
        ListInquiries(status=inquiry_status, limit=limit, cursor=cursor),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    return ListInquiriesResponse(
        items=[
            InquirySummaryResponse(
                inquiry_id=summary.inquiry_id,
                actor_id=summary.actor_id,
                execution_id=summary.execution_id,
                objective=summary.objective,
                execution_step_count=summary.execution_step_count,
                status=summary.status,
                conclusion=summary.conclusion,
                observed_step_count=summary.observed_step_count,
                execution_ended=summary.execution_ended,
                proposal_id=summary.proposal_id,
                created_at=summary.created_at,
                claimed_at=summary.claimed_at,
                answered_at=summary.answered_at,
            )
            for summary in page.items
        ],
        next_cursor=page.next_cursor,
    )
