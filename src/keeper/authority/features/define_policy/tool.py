"""MCP door for defining a policy.

The same handler the HTTP route uses. The handler is fetched per call
rather than at registration, so it sees the bundle the lifespan wired.

No idempotency key. MCP has no client-supplied retry tag to carry one,
so the wrapped handler is called with None and behaves as the bare one.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, Field

from keeper.authority.aggregates.policy import Permission
from keeper.authority.features.define_policy.command import DefinePolicy
from keeper.authority.features.define_policy.handler import IdempotentHandler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class PermissionInput(BaseModel):
    """One principal may issue one command."""

    principal_id: UUID
    command_name: str = Field(min_length=1, max_length=200)


class DefinePolicyOutput(BaseModel):
    """What the tool hands back."""

    policy_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], IdempotentHandler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="define_policy",
        description="Define a policy holding the given permissions, and return its id.",
    )
    async def define_policy_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        permissions: list[PermissionInput],
    ) -> DefinePolicyOutput:
        handler = get_handler()
        policy_id = await handler(
            DefinePolicy(
                permissions=frozenset(
                    Permission(principal_id=p.principal_id, command_name=p.command_name)
                    for p in permissions
                )
            ),
            principal_id=get_mcp_principal_id(ctx),
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return DefinePolicyOutput(policy_id=policy_id)
