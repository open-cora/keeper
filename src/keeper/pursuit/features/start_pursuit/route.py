"""HTTP door for starting a pursuit.

`POST /pursuits`, carrying the goal, the beamline, the scopes and the
budget.

The one call in this system where a person hands a machine a standing
permission, so the body is deliberately all required and has no defaults.
A field this route filled in for a caller would be this system deciding
part of its own authorization.

`budget` is an object keyed by dimension rather than a list of pairs or a
row of nullable fields, because the dimensions a deployment cares about
differ and a pursuit bounded only in tokens is as legitimate as one
bounded only in hours. At least one is required, which is enforced on the
value object rather than here, so the same refusal reaches the MCP surface
and the fold.

The bounds on the goal and the beamline are declared here as well as on
the value objects: this one turns an over-long goal into FastAPI's
standard 422 before a command exists, and the value object is what holds
for every other way into the decider.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, Field

from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)
from keeper.pursuit.aggregates.pursuit import (
    PURSUIT_BEAMLINE_MAX_LENGTH,
    PURSUIT_GOAL_MAX_LENGTH,
    PURSUIT_MAX_SCOPES,
    PURSUIT_SCOPE_MAX_LENGTH,
    Budget,
    BudgetDimension,
    PursuitBeamline,
    PursuitGoal,
)
from keeper.pursuit.features.start_pursuit.command import StartPursuit
from keeper.pursuit.features.start_pursuit.handler import IdempotentHandler


class StartPursuitRequest(BaseModel):
    """What is being authorized, and how far it may go.

    `scopes` is what the loop may drive and is the narrower of the two
    safety-bearing fields, so it is required rather than defaulted to
    everything. There is no way to spell "any scope" and that is
    deliberate.
    """

    goal: str = Field(
        min_length=1,
        max_length=PURSUIT_GOAL_MAX_LENGTH,
        description="What the loop is toward. Every inquiry it opens carries this unchanged.",
    )
    beamline: str = Field(
        min_length=1,
        max_length=PURSUIT_BEAMLINE_MAX_LENGTH,
        description="Which beamline everything inside this pursuit runs at, such as 2-bm.",
    )
    scopes: list[Annotated[str, Field(min_length=1, max_length=PURSUIT_SCOPE_MAX_LENGTH)]] = Field(
        min_length=1,
        max_length=PURSUIT_MAX_SCOPES,
        description="What the loop may drive. There is no way to spell any scope.",
    )
    budget: dict[BudgetDimension, int] = Field(
        min_length=1,
        description=(
            "Bounded consumption, keyed by dimension, whichever runs out first. "
            "At least one, and every limit positive."
        ),
    )


class StartPursuitResponse(BaseModel):
    """The id of the pursuit that was authorized."""

    pursuit_id: UUID


def _get_handler(request: Request) -> IdempotentHandler:
    handler: IdempotentHandler = request.app.state.pursuit.start_pursuit
    return handler


router = APIRouter(tags=["pursuit"])


@router.post(
    "/pursuits",
    status_code=status.HTTP_201_CREATED,
    response_model=StartPursuitResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The goal, the beamline, the scopes or the budget is not well-formed.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not start pursuits.",
        },
    },
    summary="Start a pursuit",
)
async def post_pursuits(
    body: StartPursuitRequest,
    handler: Annotated[IdempotentHandler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Replay the same key to get the same pursuit back, not a second one.",
        ),
    ] = None,
) -> StartPursuitResponse:
    pursuit_id = await handler(
        StartPursuit(
            goal=PursuitGoal(body.goal),
            beamline=PursuitBeamline(body.beamline),
            scopes=tuple(body.scopes),
            budget=Budget(dict(body.budget)),
        ),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
        idempotency_key=idempotency_key,
    )
    return StartPursuitResponse(pursuit_id=pursuit_id)
