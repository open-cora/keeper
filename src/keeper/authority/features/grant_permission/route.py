"""HTTP door for granting a permission.

`POST /policies/{policy_id}/permissions`, with the one pair being added.

The path nests the sub-resource under its parent, and the verb is left
off because the method already carries it: posting to a collection adds
to it.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from keeper.authority.aggregates.policy import Permission
from keeper.authority.features.grant_permission.command import GrantPolicyPermission
from keeper.authority.features.grant_permission.handler import Handler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class GrantPolicyPermissionRequest(BaseModel):
    """The one permission being added."""

    principal_id: UUID
    command_name: str = Field(min_length=1, max_length=200)


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.authority.grant_permission
    return handler


router = APIRouter(tags=["authority"])


@router.post(
    "/policies/{policy_id}/permissions",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not change this policy.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No policy has that id.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "The permission is already held, or the policy moved underneath.",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "The grantee is the system principal, which cannot hold one.",
        },
    },
    summary="Grant a permission",
)
async def post_policy_permissions(
    policy_id: UUID,
    body: GrantPolicyPermissionRequest,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> None:
    await handler(
        GrantPolicyPermission(
            policy_id=policy_id,
            permission=Permission(principal_id=body.principal_id, command_name=body.command_name),
        ),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
