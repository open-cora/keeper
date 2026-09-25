"""HTTP door for revoking a permission.

`DELETE /policies/{policy_id}/permissions/{principal_id}/{command_name}`.

A permission has no id of its own: the pair IS its identity, so both
halves are in the path and the permission is addressable the way any
other member of a collection is. The method carries the verb, which is
what makes this the mirror of the grant posting to the same collection
rather than the mirror of Access's `/actors/{id}/deactivate`, where the
verb has to be in the path because no sub-resource is being removed.

Two alternatives were available and are worse. A DELETE carrying a
request body is legal and widely mishandled by proxies and client
libraries, and it hides the identity of the thing being removed inside
the envelope. A `/permissions/revoke` verb segment would put the method
in the path while using POST, which says a collection is being added to.

The path can only address a command name with no slash in it. Every
command name this build issues is a Python class name, so a permission
naming anything else is one that already can never match a request, and
the MCP tool can still remove it.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from keeper.authority.aggregates.policy import Permission
from keeper.authority.features.revoke_permission.command import RevokePolicyPermission
from keeper.authority.features.revoke_permission.handler import Handler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.authority.revoke_permission
    return handler


router = APIRouter(tags=["authority"])


@router.delete(
    "/policies/{policy_id}/permissions/{principal_id}/{command_name}",
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
            "description": "The permission is not held, or the policy moved underneath.",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "Removing it would leave nobody able to change the policy.",
        },
    },
    summary="Revoke a permission",
)
async def delete_policy_permission(
    policy_id: UUID,
    principal_id: UUID,
    command_name: str,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    caller_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> None:
    await handler(
        RevokePolicyPermission(
            policy_id=policy_id,
            permission=Permission(principal_id=principal_id, command_name=command_name),
        ),
        principal_id=caller_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
