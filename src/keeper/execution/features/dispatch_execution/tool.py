"""MCP door for dispatching an execution.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

No idempotency key. MCP has no client-supplied retry tag to carry one,
so the wrapped handler is called with None and behaves as the bare one.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.execution.features.dispatch_execution.command import DispatchExecution
from keeper.execution.features.dispatch_execution.handler import IdempotentHandler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class DispatchExecutionOutput(BaseModel):
    """What the tool hands back."""

    execution_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], IdempotentHandler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="dispatch_execution",
        description=(
            "Hand a procedure out to be driven, and return the id of the execution "
            "that records it. The execution starts dispatched and nothing is running "
            "it until something claims it."
        ),
    )
    async def dispatch_execution_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        procedure_id: UUID,
    ) -> DispatchExecutionOutput:
        handler = get_handler()
        execution_id = await handler(
            DispatchExecution(procedure_id=procedure_id),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return DispatchExecutionOutput(execution_id=execution_id)
