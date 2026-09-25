"""HTTP door for deactivating an actor.

`POST /actors/{actor_id}/deactivate`, with no body. The id is in the path
because it names the thing being acted on, and deactivation takes no
other input.

A verb in the path rather than `PATCH /actors/{id}` with a state field.
The two are not equivalent here: a PATCH says what the actor should look
like afterwards and invites a second field later, while this endpoint
names one transition that the domain either allows or refuses.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from keeper.access.features.deactivate_actor.command import DeactivateActor
from keeper.access.features.deactivate_actor.handler import Handler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.access.deactivate_actor
    return handler


router = APIRouter(tags=["access"])


@router.post(
    "/actors/{actor_id}/deactivate",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not deactivate actors.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No actor has been registered under this id.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "The actor is already inactive, or was changed concurrently.",
        },
    },
    summary="Deactivate an actor",
)
async def post_actor_deactivate(
    actor_id: UUID,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> None:
    await handler(
        DeactivateActor(actor_id=actor_id),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
