"""HTTP door for reactivating an actor.

`POST /actors/{actor_id}/reactivate`, with no body, mirroring the
deactivating route. A verb in the path for the same reason: this names
one transition the domain either allows or refuses, rather than
describing a state the actor should end up in.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from keeper.access.features.reactivate_actor.command import ReactivateActor
from keeper.access.features.reactivate_actor.handler import Handler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.access.reactivate_actor
    return handler


router = APIRouter(tags=["access"])


@router.post(
    "/actors/{actor_id}/reactivate",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not reactivate actors.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No actor has been registered under this id.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "The actor is already active, or was changed concurrently.",
        },
    },
    summary="Reactivate an actor",
)
async def post_actor_reactivate(
    actor_id: UUID,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> None:
    await handler(
        ReactivateActor(actor_id=actor_id),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
