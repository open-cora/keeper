"""MCP door for reading a policy.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.authority.aggregates.policy import sorted_permissions
from keeper.authority.features.get_policy.handler import Handler
from keeper.authority.features.get_policy.query import GetPolicy
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class PermissionOutput(BaseModel):
    """One principal may issue one command."""

    principal_id: UUID
    command_name: str


class GetPolicyOutput(BaseModel):
    """A policy as this system currently holds it."""

    policy_id: UUID
    permissions: list[PermissionOutput]


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="get_policy",
        description="Read a policy by id, and every command each principal may issue under it.",
    )
    async def get_policy_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        policy_id: UUID,
    ) -> GetPolicyOutput:
        handler = get_handler()
        policy = await handler(
            GetPolicy(policy_id=policy_id),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return GetPolicyOutput(
            policy_id=policy.id,
            permissions=[
                PermissionOutput(principal_id=p.principal_id, command_name=p.command_name)
                for p in sorted_permissions(policy.permissions)
            ],
        )
