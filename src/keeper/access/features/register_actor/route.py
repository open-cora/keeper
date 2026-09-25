"""HTTP door for registering an actor.

`POST /actors`, with no body. The endpoint's whole job is to mint an
identity, and an actor carries nothing else the caller supplies, so
there is nothing for a request body to hold.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel

from keeper.access.features.register_actor.command import RegisterActor
from keeper.access.features.register_actor.handler import IdempotentHandler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class RegisterActorResponse(BaseModel):
    """The id of the actor that was created."""

    actor_id: UUID


def _get_handler(request: Request) -> IdempotentHandler:
    handler: IdempotentHandler = request.app.state.access.register_actor
    return handler


router = APIRouter(tags=["access"])


@router.post(
    "/actors",
    status_code=status.HTTP_201_CREATED,
    response_model=RegisterActorResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not register actors.",
        },
    },
    summary="Register an actor",
)
async def post_actors(
    handler: Annotated[IdempotentHandler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Replay the same key to get the same actor back, not a second one.",
        ),
    ] = None,
) -> RegisterActorResponse:
    actor_id = await handler(
        RegisterActor(),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
        idempotency_key=idempotency_key,
    )
    return RegisterActorResponse(actor_id=actor_id)
