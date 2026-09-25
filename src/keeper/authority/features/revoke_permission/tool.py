"""MCP door for revoking a permission.

The same handler the HTTP route uses. The handler is fetched per call
rather than at registration, so it sees the bundle the lifespan wired.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.authority.aggregates.policy import Permission
from keeper.authority.features.revoke_permission.command import RevokePolicyPermission
from keeper.authority.features.revoke_permission.handler import Handler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class RevokePolicyPermissionOutput(BaseModel):
    """What the tool hands back.

    The handler returns nothing, so this reports which pair was removed
    rather than inventing a result. An MCP client has no status code to
    read, so an empty answer would be indistinguishable from a call that
    did not happen.
    """

    policy_id: UUID
    principal_id: UUID
    command_name: str


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="revoke_permission",
        description="Stop one principal issuing one command under a policy.",
    )
    async def revoke_permission_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        policy_id: UUID,
        principal_id: UUID,
        command_name: str,
    ) -> RevokePolicyPermissionOutput:
        handler = get_handler()
        await handler(
            RevokePolicyPermission(
                policy_id=policy_id,
                permission=Permission(principal_id=principal_id, command_name=command_name),
            ),
            principal_id=get_mcp_principal_id(ctx),
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return RevokePolicyPermissionOutput(
            policy_id=policy_id, principal_id=principal_id, command_name=command_name
        )
