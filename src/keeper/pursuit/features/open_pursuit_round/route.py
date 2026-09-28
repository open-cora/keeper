"""HTTP door for opening a round of a pursuit.

`POST /pursuits/{pursuit_id}/rounds`, carrying the execution to ask about.

A POST to a collection, because each call adds a round to the list a
pursuit accumulates. The response carries both the number the round got
and the inquiry that went with it, which are the two things a caller needs
next: the number to close the round with, and the inquiry to wait on.

There is nothing in the body but the execution. The question is the
pursuit's goal, unchanged every round, so a caller has nothing to phrase.

No `Idempotency-Key`. A second round about one execution is refused by the
pursuit itself, so the wrapper would only turn a 409 into a repeat of the
first answer. That is worth having for a charge, where a replay would
spend the budget twice, and worth nothing here.
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
from keeper.pursuit.features.open_pursuit_round.command import OpenPursuitRound
from keeper.pursuit.features.open_pursuit_round.handler import Handler


class OpenPursuitRoundRequest(BaseModel):
    """Which execution this round observes."""

    execution_id: UUID = Field(
        description=(
            "The execution to ask about. It need not have ended; the inquiry "
            "records how much of it the thinker actually saw."
        )
    )


class OpenPursuitRoundResponse(BaseModel):
    """The round that was opened, and the question that went with it."""

    pursuit_id: UUID
    inquiry_id: UUID = Field(description="The question a thinker should now claim and answer.")


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.pursuit.open_pursuit_round
    return handler


router = APIRouter(tags=["pursuit"])


@router.post(
    "/pursuits/{pursuit_id}/rounds",
    status_code=status.HTTP_201_CREATED,
    response_model=OpenPursuitRoundResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not open rounds.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No pursuit with that id, or no execution with that id.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": (
                "The pursuit has stopped, has spent one of its budget "
                "dimensions, or has already asked about that execution."
            ),
        },
    },
    summary="Open a round of a pursuit",
)
async def post_pursuit_round(
    pursuit_id: UUID,
    body: OpenPursuitRoundRequest,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> OpenPursuitRoundResponse:
    inquiry_id = await handler(
        OpenPursuitRound(pursuit_id=pursuit_id, execution_id=body.execution_id),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    return OpenPursuitRoundResponse(pursuit_id=pursuit_id, inquiry_id=inquiry_id)
