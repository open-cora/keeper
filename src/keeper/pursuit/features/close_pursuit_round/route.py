"""HTTP door for closing a round of a pursuit.

`POST /pursuits/{pursuit_id}/rounds/{round_index}/close`, with no body.

No body, because there is nothing for a caller to say. The conclusion is
already on the inquiry this round opened, and a field here would let a
caller make a pursuit act on an answer nobody gave.

200 rather than 201 or 204. Something may have been created, an execution,
and often nothing was, so neither of the other two is honest for both. The
response says which happened, because that is what a driver branches on to
decide whether to keep going.
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
from keeper.pursuit.aggregates.pursuit import RoundOutcome
from keeper.pursuit.features.close_pursuit_round.command import ClosePursuitRound
from keeper.pursuit.features.close_pursuit_round.handler import Handler


class ClosePursuitRoundResponse(BaseModel):
    """What the round came to, and the work it became if it became any."""

    pursuit_id: UUID
    round_index: int
    outcome: RoundOutcome = Field(
        description=(
            "Advanced means a run was dispatched and the pursuit carries on. "
            "Completed means the objective is met and it has stopped. Stalled "
            "and Referred both mean it is held until a person resumes it."
        )
    )
    dispatched_id: UUID | None = Field(
        default=None, description="The execution this round caused, when it caused one."
    )


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.pursuit.close_pursuit_round
    return handler


router = APIRouter(tags=["pursuit"])


@router.post(
    "/pursuits/{pursuit_id}/rounds/{round_index}/close",
    response_model=ClosePursuitRoundResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not close rounds.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": ("No pursuit with that id, or the records the round cites are gone."),
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": (
                "The pursuit is not running, there is no such round, it has "
                "already closed, or its inquiry carries no answer yet."
            ),
        },
    },
    summary="Close a round of a pursuit",
)
async def post_pursuit_round_close(
    pursuit_id: UUID,
    round_index: int,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> ClosePursuitRoundResponse:
    closed = await handler(
        ClosePursuitRound(pursuit_id=pursuit_id, round_index=round_index),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    return ClosePursuitRoundResponse(
        pursuit_id=pursuit_id,
        round_index=round_index,
        outcome=closed.outcome,
        dispatched_id=closed.dispatched_id,
    )
