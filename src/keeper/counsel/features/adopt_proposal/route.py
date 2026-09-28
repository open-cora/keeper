"""HTTP door for adopting a proposal.

`POST /proposals/{proposal_id}/adopt`, carrying where the work will run
and what it may touch.

Returns the execution it dispatched, which is the one thing a caller
cannot work out for itself and the thing it will watch. A 201 rather
than the 204 the sibling transition returns, because this call creates
records where taking one only joins two that existed.

The body is required, and both of its fields are, because a proposal
does not carry either and nothing here can derive them. That is not a
gap in the proposal: a beamline is implied by a device prefix this
system deliberately does not parse, and a run that declared no
devices would be a step believed to touch nothing, which is a step that
can run beside another over the same motor.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, Field

from keeper.counsel.features.adopt_proposal.command import AdoptProposal
from keeper.counsel.features.adopt_proposal.handler import IdempotentHandler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class AdoptProposalRequest(BaseModel):
    """Where the adopted run goes, and what it may touch."""

    beamline: str = Field(min_length=1)
    scopes: tuple[str, ...] = Field(min_length=1)


class AdoptProposalResponse(BaseModel):
    """The execution this adoption dispatched."""

    execution_id: UUID


def _get_handler(request: Request) -> IdempotentHandler:
    handler: IdempotentHandler = request.app.state.counsel.adopt_proposal
    return handler


router = APIRouter(tags=["counsel"])


@router.post(
    "/proposals/{proposal_id}/adopt",
    status_code=status.HTTP_201_CREATED,
    response_model=AdoptProposalResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The beamline or the devices fall outside what a procedure "
            "stores, or the proposal's values no longer satisfy its operation's schema.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not adopt proposals.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No proposal has that id, or its operation is gone.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "The proposal is no longer open, or was adopted concurrently.",
        },
    },
    summary="Adopt a proposal",
)
async def post_proposal_adopt(
    proposal_id: UUID,
    body: AdoptProposalRequest,
    handler: Annotated[IdempotentHandler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Replay the same key to get the same execution back, not a second one.",
        ),
    ] = None,
) -> AdoptProposalResponse:
    execution_id = await handler(
        AdoptProposal(
            proposal_id=proposal_id,
            beamline=body.beamline,
            scopes=tuple(body.scopes),
        ),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
        idempotency_key=idempotency_key,
    )
    return AdoptProposalResponse(execution_id=execution_id)
