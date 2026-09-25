"""HTTP door for reading a policy.

`GET /policies/{policy_id}`. Returns the id and every (principal,
command) pair the policy permits, which is the whole of what a policy
is.

The pairs come back in the order `sorted_permissions` imposes, not in
the order a set happens to iterate. A client polling this endpoint would
otherwise see the same rulebook shuffle between calls and have no way to
tell that apart from an edit.

There is no field saying whether the policy can still be changed. It is
the question an operator most wants answered, and the answer today is
always yes: both writing paths refuse to produce a policy nobody can
change, so a `governable` field would be a constant dressed as data. The
pairs are what varies, so the pairs are what is returned.

The state is folded from the stream on every call. A policy is a handful
of rows, and the authorization adapter pays the same cost per request,
so a summary table would be machinery maintained ahead of a need.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from keeper.authority.aggregates.policy import sorted_permissions
from keeper.authority.features.get_policy.handler import Handler
from keeper.authority.features.get_policy.query import GetPolicy
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class PermissionResponse(BaseModel):
    """One principal may issue one command."""

    principal_id: UUID
    command_name: str


class GetPolicyResponse(BaseModel):
    """A policy as this system currently holds it."""

    policy_id: UUID
    permissions: list[PermissionResponse]


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.authority.get_policy
    return handler


router = APIRouter(tags=["authority"])


@router.get(
    "/policies/{policy_id}",
    response_model=GetPolicyResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read policies.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No policy has that id.",
        },
    },
    summary="Read a policy",
)
async def get_policy(
    policy_id: UUID,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> GetPolicyResponse:
    policy = await handler(
        GetPolicy(policy_id=policy_id),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    return GetPolicyResponse(
        policy_id=policy.id,
        permissions=[
            PermissionResponse(principal_id=p.principal_id, command_name=p.command_name)
            for p in sorted_permissions(policy.permissions)
        ],
    )
