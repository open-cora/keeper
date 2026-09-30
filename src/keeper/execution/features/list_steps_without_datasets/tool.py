"""MCP door for listing runs whose output nothing recorded.

The same handler the HTTP route uses. The handler is fetched per call
rather than at registration, so it sees the bundle the lifespan wired
rather than whatever existed when the server was built.

An agent asking this is asking whether the record of a facility's work
is complete, which is a reasonable thing to ask before drawing any
conclusion from a dataset listing: an empty listing means either that
nothing was produced or that nothing was written down, and only this
tells the two apart.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.execution.aggregates.execution import ExecutionBeamline
from keeper.execution.features.list_steps_without_datasets.handler import Handler
from keeper.execution.features.list_steps_without_datasets.query import (
    DEFAULT_PAGE_SIZE,
    ListStepsWithoutDatasets,
)
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class UnfiledStepOutput(BaseModel):
    """One run whose output nothing recorded."""

    step_id: UUID
    execution_id: UUID
    index: int
    describes: str
    beamline: str
    outcome: str | None
    engine_reference: str | None
    reported_at: datetime | None


class ListStepsWithoutDatasetsOutput(BaseModel):
    """One page, and the cursor that continues it."""

    items: list[UnfiledStepOutput]
    next_cursor: str | None


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="list_steps_without_datasets",
        description=(
            "List runs that produced data no dataset records the location of, newest "
            "first. A row means the record is incomplete rather than that data was "
            "lost: the step ran and the engine wrote its output under the reference "
            "shown. Give a beamline to narrow to one station."
        ),
    )
    async def list_steps_without_datasets_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        beamline: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> ListStepsWithoutDatasetsOutput:
        handler = get_handler()
        page = await handler(
            ListStepsWithoutDatasets(
                beamline=ExecutionBeamline(beamline) if beamline is not None else None,
                limit=limit,
                cursor=cursor,
            ),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return ListStepsWithoutDatasetsOutput(
            items=[
                UnfiledStepOutput(
                    step_id=summary.step_id,
                    execution_id=summary.execution_id,
                    index=summary.index,
                    describes=summary.describes,
                    beamline=summary.beamline.value,
                    outcome=summary.outcome,
                    engine_reference=summary.engine_reference,
                    reported_at=summary.reported_at,
                )
                for summary in page.items
            ],
            next_cursor=page.next_cursor,
        )
