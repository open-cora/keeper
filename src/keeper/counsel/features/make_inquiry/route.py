"""HTTP door for making an inquiry.

`POST /inquiries`, carrying the execution the question is about and the
question itself.

A POST that creates the thing it names, the way `POST /proposals` next door
does: the request IS the asking, so whoever wanted to know has asked by the
time this returns.

There is no `occurred_at` in the body for that reason, and no asker either.
Both are the handler's, the first from the clock and the second from the
authenticated principal. There is no step count in the body either, because
the handler reads it off the execution rather than believing a caller about
how much there was to see.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, Field

from keeper.counsel.aggregates.inquiry import INQUIRY_OBJECTIVE_MAX_LENGTH
from keeper.counsel.features.make_inquiry.command import MakeInquiry
from keeper.counsel.features.make_inquiry.handler import IdempotentHandler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class MakeInquiryRequest(BaseModel):
    """The question being put.

    `objective` declares the same bound the value object enforces, so an
    over-long one is refused here with a message naming the field rather
    than in a decider with a message naming the domain. Both checks are
    real: this one does not reach the MCP surface.
    """

    execution_id: UUID
    objective: str = Field(min_length=1, max_length=INQUIRY_OBJECTIVE_MAX_LENGTH)


class MakeInquiryResponse(BaseModel):
    """The id of the inquiry that was made."""

    inquiry_id: UUID


def _get_handler(request: Request) -> IdempotentHandler:
    handler: IdempotentHandler = request.app.state.counsel.make_inquiry
    return handler


router = APIRouter(tags=["counsel"])


@router.post(
    "/inquiries",
    status_code=status.HTTP_201_CREATED,
    response_model=MakeInquiryResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The objective is empty after trimming, or too long.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not make inquiries.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No execution has that id.",
        },
    },
    summary="Make an inquiry",
)
async def post_inquiries(
    body: MakeInquiryRequest,
    handler: Annotated[IdempotentHandler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Replay the same key to get the same inquiry back, not a second one.",
        ),
    ] = None,
) -> MakeInquiryResponse:
    inquiry_id = await handler(
        MakeInquiry(execution_id=body.execution_id, objective=body.objective),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
        idempotency_key=idempotency_key,
    )
    return MakeInquiryResponse(inquiry_id=inquiry_id)
