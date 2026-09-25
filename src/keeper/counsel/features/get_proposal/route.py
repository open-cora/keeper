"""HTTP door for reading a proposal.

`GET /proposals/{proposal_id}`. Returns who advised, what they put
forward, and the acquisition that took it if one has.

`execution_id` and `step_id` are null while the proposal is open, and
that null is the status. There is no status field, because a two-valued
enum beside a nullable field would be the same fact written twice. A
caller asking whether a proposal is still open asks whether the step is
there.

Both ids come back, because a step is an entity inside an execution
rather than a stream of its own, so a caller given the step alone could
not read it.

The parameters come back exactly as they were stored, not re-rendered. A
caller comparing what was proposed against what an engine was given has
to be working from the record rather than from a rendering of it.

The state is folded from the stream on every call. A proposal is one row
or two, so a summary table would be machinery maintained ahead of a
need. That changes with the query this context exists for, which is
which proposals are still open, and which a fold cannot serve because it
cannot name the stream to fold.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from keeper.counsel.features.get_proposal.handler import Handler
from keeper.counsel.features.get_proposal.query import GetProposal
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class GetProposalResponse(BaseModel):
    """A proposal as this system currently holds it."""

    proposal_id: UUID
    actor_id: UUID
    plan_id: UUID
    parameters: dict[str, Any]
    execution_id: UUID | None
    step_id: UUID | None


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.counsel.get_proposal
    return handler


router = APIRouter(tags=["counsel"])


@router.get(
    "/proposals/{proposal_id}",
    response_model=GetProposalResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read proposals.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No proposal has that id.",
        },
    },
    summary="Read a proposal",
)
async def get_proposal(
    proposal_id: UUID,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> GetProposalResponse:
    proposal = await handler(
        GetProposal(proposal_id=proposal_id),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    return GetProposalResponse(
        proposal_id=proposal.id,
        actor_id=proposal.actor_id,
        plan_id=proposal.plan_id,
        parameters=proposal.parameters,
        execution_id=proposal.execution_id,
        step_id=proposal.step_id,
    )
