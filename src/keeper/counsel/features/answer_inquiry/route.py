"""HTTP door for answering an inquiry.

`POST /inquiries/{inquiry_id}/answer`, carrying the conclusion, how much of
the execution the thinker had in front of it, and the proposal if it wrote
one.

The body is required here where the claim's is optional, because three of
its fields are the substance of the act. An answer with no conclusion is
not an answer, and an answer with no observation boundary is one nobody can
weigh later.

Claiming first is not required. A thinker handed its question answers
straight from open, which the decider allows deliberately.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from keeper.counsel.aggregates.inquiry import InquiryConclusion
from keeper.counsel.features.answer_inquiry.command import AnswerInquiry
from keeper.counsel.features.answer_inquiry.handler import Handler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.counsel.answer_inquiry
    return handler


class AnswerInquiryRequest(BaseModel):
    """What the thinker concluded, and how much it saw.

    `conclusion` is typed as the closed set, so a fifth word is refused at
    the wire with a message listing the four rather than reaching a decider
    that would have to.

    `observed_step_count` and `execution_ended` are required. They are the
    observation boundary, and making them optional would let the commonest
    caller omit the thing the record was extended to hold.

    `proposal_id` belongs with a Propose conclusion and with nothing else.
    The decider refuses both halves of that rule, since neither can be
    expressed as a field constraint.
    """

    conclusion: InquiryConclusion
    observed_step_count: int = Field(ge=0)
    execution_ended: bool
    proposal_id: UUID | None = None
    occurred_at: datetime | None = None


router = APIRouter(tags=["counsel"])


@router.post(
    "/inquiries/{inquiry_id}/answer",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The observation boundary is impossible, the conclusion and the "
            "proposal disagree, or the supplied occurred_at carried no timezone.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not answer inquiries.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No inquiry has that id, or no proposal has the one named.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "The inquiry already has an answer, or was answered concurrently.",
        },
    },
    summary="Answer an inquiry",
)
async def post_inquiry_answer(
    inquiry_id: UUID,
    body: AnswerInquiryRequest,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> None:
    await handler(
        AnswerInquiry(
            inquiry_id=inquiry_id,
            conclusion=body.conclusion,
            observed_step_count=body.observed_step_count,
            execution_ended=body.execution_ended,
            proposal_id=body.proposal_id,
            occurred_at=body.occurred_at,
        ),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
