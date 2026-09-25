"""HTTP door for finding proposals.

`GET /proposals`, optionally narrowed to the open ones, newest first,
paged.

The read that carries this context's purpose. `GET /proposals/{id}`
answers a question that already names the proposal; this one answers
"what has been put forward that nobody acted on", which is the question
somebody looking at the system actually has.

Rows carry both timestamps and the single read carries neither. That is
a decision on each side rather than an oversight on one: a list is read
to find something, and when a proposal was made is how a person
recognises the one they meant. A single read already names it.

Rows do not carry the parameters, which the single read does. They are
unbounded, and a page of fifty would be mostly parameters. Finding the
proposal is what tells a caller which id to read for those.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel

from keeper.counsel.features.list_proposals.handler import Handler
from keeper.counsel.features.list_proposals.query import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ListProposals,
)
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class ProposalSummaryResponse(BaseModel):
    """A proposal as a list shows it.

    No parameters. A caller that wants the values reads the one proposal
    it cares about, which is what the id in this row is for.
    """

    proposal_id: UUID
    actor_id: UUID
    plan_id: UUID
    execution_id: UUID | None
    step_id: UUID | None
    created_at: datetime
    taken_at: datetime | None


class ListProposalsResponse(BaseModel):
    """One page of proposals, and how to ask for the next."""

    items: list[ProposalSummaryResponse]
    next_cursor: str | None


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.counsel.list_proposals
    return handler


router = APIRouter(tags=["counsel"])


@router.get(
    "/proposals",
    response_model=ListProposalsResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read proposals.",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "The cursor is not one this system issued.",
        },
    },
    summary="Find proposals",
)
async def get_proposals(
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    is_open: Annotated[
        bool | None,
        Query(description="True for proposals no run has taken, false for the rest."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query(description="Continue a previous page.")] = None,
) -> ListProposalsResponse:
    page = await handler(
        ListProposals(is_open=is_open, limit=limit, cursor=cursor),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    return ListProposalsResponse(
        items=[
            ProposalSummaryResponse(
                proposal_id=summary.proposal_id,
                actor_id=summary.actor_id,
                plan_id=summary.plan_id,
                execution_id=summary.execution_id,
                step_id=summary.step_id,
                created_at=summary.created_at,
                taken_at=summary.taken_at,
            )
            for summary in page.items
        ],
        next_cursor=page.next_cursor,
    )
