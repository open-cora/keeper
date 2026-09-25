"""MCP door for relaying an engine's account of one step's run.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.execution.aggregates.execution import EngineReport
from keeper.execution.features.report_step_run.command import ReportStepRun
from keeper.execution.features.report_step_run.handler import Handler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class ReportStepRunOutput(BaseModel):
    """What the tool hands back: the step it moved."""

    execution_id: UUID
    step_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="report_step_run",
        description=(
            "Relay what an engine did to the run one step opened: Started, "
            "Paused, Resumed, Completed, Aborted or Failed. This is the "
            "engine's account, which is separate from what the driver saw and "
            "may disagree with it. A move opens no run and has none of this."
        ),
    )
    async def report_step_run_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        execution_id: UUID,
        step_id: UUID,
        reported: EngineReport,
        engine_reference: str | None = None,
        occurred_at: datetime | None = None,
    ) -> ReportStepRunOutput:
        handler = get_handler()
        await handler(
            ReportStepRun(
                execution_id=execution_id,
                step_id=step_id,
                reported=reported,
                engine_reference=engine_reference,
                occurred_at=occurred_at,
            ),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return ReportStepRunOutput(execution_id=execution_id, step_id=step_id)
