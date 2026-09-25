"""HTTP door for making a proposal.

`POST /proposals`, carrying the plan a run is proposed of and the values
proposed for it.

A POST that creates the thing it names, unlike `POST /runs` and
`POST /datasets` next door, which create records of acts that already
happened elsewhere. Here the request IS the act: whoever proposed
something has done so by the time this returns.

There is no `occurred_at` in the body for that reason, and no proposer
either. Both are the handler's, the first from the clock and the second
from the authenticated principal.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, Field

from keeper.counsel.features.make_proposal.command import MakeProposal
from keeper.counsel.features.make_proposal.handler import IdempotentHandler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class MakeProposalRequest(BaseModel):
    """The run being put forward.

    `parameters` defaults to empty, matching a plan whose schema
    constrains nothing. A caller proposing a routine that takes no
    values sends nothing rather than an empty object it had to know to
    write.
    """

    plan_id: UUID
    parameters: dict[str, Any] = Field(default_factory=dict)


class MakeProposalResponse(BaseModel):
    """The id of the proposal that was made."""

    proposal_id: UUID


def _get_handler(request: Request) -> IdempotentHandler:
    handler: IdempotentHandler = request.app.state.counsel.make_proposal
    return handler


router = APIRouter(tags=["counsel"])


@router.post(
    "/proposals",
    status_code=status.HTTP_201_CREATED,
    response_model=MakeProposalResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The values do not satisfy the plan's schema.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not make proposals.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No plan has that id.",
        },
    },
    summary="Make a proposal",
)
async def post_proposals(
    body: MakeProposalRequest,
    handler: Annotated[IdempotentHandler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Replay the same key to get the same proposal back, not a second one.",
        ),
    ] = None,
) -> MakeProposalResponse:
    proposal_id = await handler(
        MakeProposal(plan_id=body.plan_id, parameters=body.parameters),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
        idempotency_key=idempotency_key,
    )
    return MakeProposalResponse(proposal_id=proposal_id)
