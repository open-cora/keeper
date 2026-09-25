"""MCP door for deactivating an actor.

The same handler the HTTP route uses. The handler is fetched per call
rather than at registration, so it sees the bundle the lifespan wired
rather than whatever existed when the server was built.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.access.features.deactivate_actor.command import DeactivateActor
from keeper.access.features.deactivate_actor.handler import Handler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class DeactivateActorOutput(BaseModel):
    """What the tool hands back.

    The id that was deactivated, echoed so a caller chaining tools has
    something to carry forward. The HTTP route returns 204 and nothing,
    because there the id is already in the URL the caller wrote.
    """

    actor_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="deactivate_actor",
        description="Switch an actor off, so it is no longer active.",
    )
    async def deactivate_actor_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        actor_id: UUID,
    ) -> DeactivateActorOutput:
        handler = get_handler()
        await handler(
            DeactivateActor(actor_id=actor_id),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return DeactivateActorOutput(actor_id=actor_id)
