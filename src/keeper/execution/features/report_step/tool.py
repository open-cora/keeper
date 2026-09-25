"""MCP door for reporting one step of an execution.

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

from keeper.execution.aggregates.execution import StepOutcome
from keeper.execution.features.report_step.command import ReportExecutionStep
from keeper.execution.features.report_step.handler import Handler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class ReportExecutionStepOutput(BaseModel):
    """The execution and the step that were reported, echoed back.

    Both, because neither alone identifies the step: an index means
    nothing without the execution it indexes into.
    """

    execution_id: UUID
    index: int


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="report_step",
        description="Record how one step of an execution ended.",
    )
    async def report_step_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        execution_id: UUID,
        index: int,
        outcome: StepOutcome,
        engine_reference: str | None = None,
        cause: str | None = None,
        occurred_at: datetime | None = None,
    ) -> ReportExecutionStepOutput:
        handler = get_handler()
        await handler(
            ReportExecutionStep(
                execution_id=execution_id,
                index=index,
                outcome=outcome,
                engine_reference=engine_reference,
                cause=cause,
                occurred_at=occurred_at,
            ),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return ReportExecutionStepOutput(execution_id=execution_id, index=index)
