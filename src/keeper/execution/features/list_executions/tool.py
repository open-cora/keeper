"""MCP door for listing executions.

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

from keeper.execution.aggregates.execution import ExecutionBeamline, ExecutionStatus
from keeper.execution.features.list_executions.handler import Handler
from keeper.execution.features.list_executions.query import DEFAULT_PAGE_SIZE, ListExecutions
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class ExecutionSummaryOutput(BaseModel):
    """An execution as a list shows it, without its steps."""

    execution_id: UUID
    procedure_id: UUID
    procedure_name: str
    beamline: str
    step_count: int
    reported_count: int
    status: ExecutionStatus
    created_at: datetime
    updated_at: datetime


class ListExecutionsOutput(BaseModel):
    """One page, and the cursor that continues it."""

    items: list[ExecutionSummaryOutput]
    next_cursor: str | None


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="list_executions",
        description=(
            "List executions newest first. Give a procedure id to see every execution "
            "dispatched for that routine. A row carries how far each got and "
            "what is happening to it; read the steps with get_execution."
        ),
    )
    async def list_executions_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        procedure_id: UUID | None = None,
        beamline: str | None = None,
        status: ExecutionStatus | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> ListExecutionsOutput:
        handler = get_handler()
        page = await handler(
            ListExecutions(
                procedure_id=procedure_id,
                beamline=ExecutionBeamline(beamline) if beamline is not None else None,
                status=status,
                limit=limit,
                cursor=cursor,
            ),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return ListExecutionsOutput(
            items=[
                ExecutionSummaryOutput(
                    execution_id=summary.execution_id,
                    procedure_id=summary.procedure_id,
                    procedure_name=summary.procedure_name,
                    beamline=summary.beamline.value,
                    step_count=summary.step_count,
                    reported_count=summary.reported_count,
                    status=summary.status,
                    created_at=summary.created_at,
                    updated_at=summary.updated_at,
                )
                for summary in page.items
            ],
            next_cursor=page.next_cursor,
        )
