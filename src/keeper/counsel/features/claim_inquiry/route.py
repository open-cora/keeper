"""HTTP door for claiming an inquiry.

`POST /inquiries/{inquiry_id}/claim`, the shape `claim_execution` uses and
for the same reason: a verb on a record that already exists, carrying at
most the moment it happened.

Optional in the lifecycle. A thinker handed its question can answer without
ever calling this, and the answer route says so.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Request, status
from pydantic import BaseModel

from keeper.counsel.features.claim_inquiry.command import ClaimInquiry
from keeper.counsel.features.claim_inquiry.handler import Handler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.counsel.claim_inquiry
    return handler


class ClaimInquiryRequest(BaseModel):
    """When the thinker took the question up, if the caller knows.

    The whole body, and the whole body is optional. Omitting it means the
    event is stamped with the moment the report arrived.
    """

    occurred_at: datetime | None = None


router = APIRouter(tags=["counsel"])


@router.post(
    "/inquiries/{inquiry_id}/claim",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The supplied occurred_at carried no timezone.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not claim inquiries.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No inquiry has that id.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "The inquiry is not open, or was claimed concurrently.",
        },
    },
    summary="Claim an inquiry",
)
async def post_inquiry_claim(
    inquiry_id: UUID,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    body: Annotated[ClaimInquiryRequest | None, Body()] = None,
) -> None:
    await handler(
        ClaimInquiry(inquiry_id=inquiry_id, occurred_at=body.occurred_at if body else None),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
