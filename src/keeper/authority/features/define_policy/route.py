"""HTTP door for defining a policy.

`POST /policies`, with the permissions the policy starts out holding.

The body takes a JSON array of pairs and the domain wants a set, so the
conversion happens here. An edge is where the difference between what a
wire format can express and what the domain means belongs: JSON has no
set, and a duplicate pair arriving twice is a fact about the request
rather than about the policy.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, Field

from keeper.authority.aggregates.policy import Permission
from keeper.authority.features.define_policy.command import DefinePolicy
from keeper.authority.features.define_policy.handler import IdempotentHandler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class PermissionBody(BaseModel):
    """One principal may issue one command, at one place or at none."""

    principal_id: UUID
    command_name: str = Field(min_length=1, max_length=200)
    beamline: str | None = Field(default=None, min_length=1, max_length=200)
    """The place this grant covers, or absent for a command that names none.

    There is no value meaning everywhere. A principal that may act at
    four beamlines holds four grants, which is a reach a reader of the
    rulebook can see rather than one hidden behind a star.

    Spelled the same here as in the granting slice on purpose. Without
    it a policy could be granted a scoped permission but never born
    with one, so a deployment authoring its first rulebook would have
    to write every scoped grant as a second call.
    """


class DefinePolicyRequest(BaseModel):
    """The permissions the new policy starts out holding.

    Required, with no default. An empty array is accepted and produces
    a policy that permits nothing, which is a usable state today and a
    deliberate one; obtaining it by leaving a key out of the body would
    not be. See the decider.
    """

    permissions: list[PermissionBody]


class DefinePolicyResponse(BaseModel):
    """The id of the policy that was created."""

    policy_id: UUID


def _get_handler(request: Request) -> IdempotentHandler:
    handler: IdempotentHandler = request.app.state.authority.define_policy
    return handler


router = APIRouter(tags=["authority"])


@router.post(
    "/policies",
    status_code=status.HTTP_201_CREATED,
    response_model=DefinePolicyResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not define policies.",
        },
    },
    summary="Define a policy",
)
async def post_policies(
    body: DefinePolicyRequest,
    handler: Annotated[IdempotentHandler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Replay the same key to get the same policy back, not a second one.",
        ),
    ] = None,
) -> DefinePolicyResponse:
    policy_id = await handler(
        DefinePolicy(
            permissions=frozenset(
                Permission(
                    principal_id=p.principal_id,
                    command_name=p.command_name,
                    beamline=p.beamline,
                )
                for p in body.permissions
            )
        ),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
        idempotency_key=idempotency_key,
    )
    return DefinePolicyResponse(policy_id=policy_id)
