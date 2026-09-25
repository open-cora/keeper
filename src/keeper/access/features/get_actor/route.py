"""HTTP door for reading an actor.

`GET /actors/{actor_id}`. Returns the id and whether the actor is
currently active, which is the whole of what an Actor is.

The state is folded from the stream on every call. That is the right
trade for one actor by id, where the stream is a handful of rows, and
the wrong one for listing or filtering actors. A query of that shape
needs a maintained summary table and belongs in its own slice.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from keeper.access.features.get_actor.handler import Handler
from keeper.access.features.get_actor.query import GetActor
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class GetActorResponse(BaseModel):
    """An actor as this system currently holds it."""

    actor_id: UUID
    active: bool


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.access.get_actor
    return handler


router = APIRouter(tags=["access"])


@router.get(
    "/actors/{actor_id}",
    response_model=GetActorResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read actors.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No actor has been registered under this id.",
        },
    },
    summary="Read an actor",
)
async def get_actor(
    actor_id: UUID,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> GetActorResponse:
    actor = await handler(
        GetActor(actor_id=actor_id),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    return GetActorResponse(actor_id=actor.id, active=actor.active)
