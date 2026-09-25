"""MCP door for claiming an execution.

The same handler the HTTP route uses. The handler is fetched per call
rather than at registration, so it sees the bundle the lifespan wired
rather than whatever existed when the server was built.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.execution.features.claim_execution.command import ClaimExecution
from keeper.execution.features.claim_execution.handler import Handler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class ClaimExecutionOutput(BaseModel):
    """The id that was ended, echoed so a caller chaining tools can carry it."""

    execution_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="claim_execution",
        description=(
            "Take up a dispatched execution, saying this caller is the one driving it. "
            "Refused if something already claimed it, which is two drivers believing "
            "they own one traversal."
        ),
    )
    async def claim_execution_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        execution_id: UUID,
        occurred_at: datetime | None = None,
    ) -> ClaimExecutionOutput:
        handler = get_handler()
        await handler(
            ClaimExecution(execution_id=execution_id, occurred_at=occurred_at),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return ClaimExecutionOutput(execution_id=execution_id)
