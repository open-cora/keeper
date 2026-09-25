"""MCP door for reactivating an actor.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.access.features.reactivate_actor.command import ReactivateActor
from keeper.access.features.reactivate_actor.handler import Handler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class ReactivateActorOutput(BaseModel):
    """The id that was reactivated, echoed for a caller chaining tools."""

    actor_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="reactivate_actor",
        description="Switch an actor back on, so it is active again.",
    )
    async def reactivate_actor_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        actor_id: UUID,
    ) -> ReactivateActorOutput:
        handler = get_handler()
        await handler(
            ReactivateActor(actor_id=actor_id),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return ReactivateActorOutput(actor_id=actor_id)
