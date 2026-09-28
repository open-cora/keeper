"""HTTP door for listing pursuits.

`GET /pursuits`, newest first, narrowed by status, by beamline, or by
neither.

The beamline filter is the one this route exists for. A pursuit authorizes
a machine to dispatch work at a beamline without asking again, so somebody
standing at that beamline needs to see exactly which loops may, and
`?beamline=2-bm&status=Running` is that question.

`?status=Held` is the other: which loops have stopped asking and are
waiting for a person. Each row says which of the two answerable
conclusions put it there, because one needs attention and the other needs
data.

The page carries a cursor rather than an offset, for the reason every list
in this tree does: a pursuit starting between two pages would shift every
row after it, and a caller walking by offset would see one twice or miss
one.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)
from keeper.pursuit.aggregates.pursuit import (
    PURSUIT_BEAMLINE_MAX_LENGTH,
    PursuitStatus,
    RoundOutcome,
)
from keeper.pursuit.features.list_pursuits.handler import Handler
from keeper.pursuit.features.list_pursuits.query import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ListPursuits,
)


class PursuitSummaryResponse(BaseModel):
    """One pursuit, as a page shows it."""

    pursuit_id: UUID
    actor_id: UUID = Field(description="Who authorized it.")
    goal: str
    beamline: str
    status: PursuitStatus
    held_for: RoundOutcome | None = Field(
        default=None,
        description=(
            "Why it is waiting, when it is. Referred means a person was asked "
            "for; Stalled means a thinker had nothing to go on."
        ),
    )
    round_count: int = Field(description="How many rounds it has opened, closed or not.")
    created_at: str
    stopped_at: str | None = Field(
        default=None,
        description="When somebody withdrew it. Absent when it stopped by concluding.",
    )


class ListPursuitsResponse(BaseModel):
    """One page, newest first, and how to ask for the next."""

    items: list[PursuitSummaryResponse]
    next_cursor: str | None = Field(
        default=None, description="Pass back as `cursor`. Absent on the last page."
    )


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.pursuit.list_pursuits
    return handler


router = APIRouter(tags=["pursuit"])


@router.get(
    "/pursuits",
    response_model=ListPursuitsResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The cursor did not decode.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read pursuits.",
        },
    },
    summary="List pursuits",
)
async def get_pursuits(
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    pursuit_status: Annotated[
        PursuitStatus | None,
        Query(alias="status", description="Only pursuits in this state."),
    ] = None,
    beamline: Annotated[
        str | None,
        Query(
            max_length=PURSUIT_BEAMLINE_MAX_LENGTH,
            description="Only pursuits authorized at this beamline, such as 2-bm.",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query(description="From a previous page.")] = None,
) -> ListPursuitsResponse:
    page = await handler(
        ListPursuits(status=pursuit_status, beamline=beamline, limit=limit, cursor=cursor),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    return ListPursuitsResponse(
        items=[
            PursuitSummaryResponse(
                pursuit_id=summary.pursuit_id,
                actor_id=summary.actor_id,
                goal=summary.goal,
                beamline=summary.beamline,
                status=summary.status,
                held_for=summary.held_for,
                round_count=summary.round_count,
                created_at=summary.created_at.isoformat(),
                stopped_at=(None if summary.stopped_at is None else summary.stopped_at.isoformat()),
            )
            for summary in page.items
        ],
        next_cursor=page.next_cursor,
    )


__all__ = ["router"]
