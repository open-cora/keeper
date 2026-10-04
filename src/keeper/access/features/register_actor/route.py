"""HTTP door for registering an actor.

`POST /actors`, with an optional body naming the id to register at.

The endpoint's ordinary job is to mint an identity, and an actor
carries nothing else the caller supplies, so the body is optional and
is normally absent. It exists for the one case where the id is not this
system's to choose: a deployment whose callers authenticate as an id
derived from their token subject needs an actor under that exact id, or
authorization refuses them whatever the policy says.

Registering at an id that is already taken is a 409, which the minting
path cannot produce.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, Field

from keeper.access.features.register_actor.command import RegisterActor
from keeper.access.features.register_actor.handler import IdempotentHandler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class RegisterActorRequest(BaseModel):
    """What the caller may say about the actor being registered."""

    actor_id: UUID | None = Field(
        default=None,
        description=(
            "Register at this id instead of a minted one. Leave it out unless the id "
            "has to match something outside this system, such as the principal id a "
            "token authenticates as."
        ),
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
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "An actor is already registered at the id the body named.",
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
    body: RegisterActorRequest | None = None,
) -> RegisterActorResponse:
    actor_id = await handler(
        RegisterActor(actor_id=None if body is None else body.actor_id),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
        idempotency_key=idempotency_key,
    )
    return RegisterActorResponse(actor_id=actor_id)
