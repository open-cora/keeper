"""HTTP door for reading one pursuit.

`GET /pursuits/{pursuit_id}`.

The response carries the whole authorization rather than a summary of it,
because every field is what somebody would be reading it to check: what
was permitted, at which beamline, over what, within what, by whom, and
whether it is still standing. A shape that left one out would send a
reader to the log.

`budget` comes back keyed by dimension, the same shape it went in as. A
list of pairs would make a client that only cares about one dimension
walk the whole thing.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)
from keeper.pursuit.aggregates.pursuit import BudgetDimension, PursuitStatus
from keeper.pursuit.features.get_pursuit.handler import Handler
from keeper.pursuit.features.get_pursuit.query import GetPursuit


class PursuitResponse(BaseModel):
    """One pursuit, as somebody checking what it may do reads it."""

    pursuit_id: UUID
    actor_id: UUID = Field(description="Who authorized it.")
    goal: str
    beamline: str
    scopes: list[str]
    budget: dict[BudgetDimension, int]
    started_at: str
    status: PursuitStatus = Field(
        description="Running while it may still authorize work, Stopped once it may not."
    )
    stopped_by: UUID | None = Field(
        default=None,
        description="Who withdrew it, when that is how it stopped.",
    )


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.pursuit.get_pursuit
    return handler


router = APIRouter(tags=["pursuit"])


@router.get(
    "/pursuits/{pursuit_id}",
    response_model=PursuitResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read pursuits.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No pursuit with that id.",
        },
    },
    summary="Read a pursuit",
)
async def get_pursuit(
    pursuit_id: UUID,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> PursuitResponse:
    pursuit = await handler(
        GetPursuit(pursuit_id=pursuit_id),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    return PursuitResponse(
        pursuit_id=pursuit.id,
        actor_id=pursuit.actor_id,
        goal=pursuit.goal.value,
        beamline=pursuit.beamline.value,
        scopes=list(pursuit.scopes),
        budget=dict(pursuit.budget.limits),
        started_at=pursuit.started_at.isoformat(),
        status=pursuit.status,
        stopped_by=pursuit.stopped_by,
    )
