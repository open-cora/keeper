"""HTTP door for resuming a pursuit.

`POST /pursuits/{pursuit_id}/resume`, with no body.

A POST to a subresource, beside withdrawing, and the pair is deliberately
symmetric: one ends the authorization and one puts it back to work, and
neither deletes anything.

No body at all. Why the pursuit was held is on the round that held it, and
why somebody decided it should carry on is a conversation rather than a
field.

No `Idempotency-Key`, beside every other transition in this tree. A
replayed resume arrives at a pursuit that is already running and is
refused, which is what a replayed transition is everywhere else here.

204 rather than the pursuit back. A caller that wants the resumed record
can read it, and returning it here would make the common case pay for the
rare one.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)
from keeper.pursuit.features.resume_pursuit.command import ResumePursuit
from keeper.pursuit.features.resume_pursuit.handler import Handler


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.pursuit.resume_pursuit
    return handler


router = APIRouter(tags=["pursuit"])


@router.post(
    "/pursuits/{pursuit_id}/resume",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not resume pursuits.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No pursuit with that id.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": (
                "The pursuit was running or had stopped, so there was nothing to resume."
            ),
        },
    },
    summary="Resume a pursuit",
)
async def post_pursuit_resumption(
    pursuit_id: UUID,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> None:
    await handler(
        ResumePursuit(pursuit_id=pursuit_id),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
