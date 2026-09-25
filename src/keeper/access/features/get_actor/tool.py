"""MCP door for reading an actor.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.access.features.get_actor.handler import Handler
from keeper.access.features.get_actor.query import GetActor
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class GetActorOutput(BaseModel):
    """An actor as this system currently holds it."""

    actor_id: UUID
    active: bool


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="get_actor",
        description="Read an actor by id, and whether it is currently active.",
    )
    async def get_actor_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        actor_id: UUID,
    ) -> GetActorOutput:
        handler = get_handler()
        actor = await handler(
            GetActor(actor_id=actor_id),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return GetActorOutput(actor_id=actor.id, active=actor.active)
