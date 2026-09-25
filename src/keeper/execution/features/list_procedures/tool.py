"""MCP door for listing procedures.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.execution.features.list_procedures.handler import Handler
from keeper.execution.features.list_procedures.query import DEFAULT_PAGE_SIZE, ListProcedures
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class ProcedureSummaryOutput(BaseModel):
    """One procedure, as a list shows it."""

    procedure_id: UUID
    name: str
    beamline: str
    step_count: int
    created_at: datetime


class ListProceduresOutput(BaseModel):
    """A page of procedures, and how to ask for the next one."""

    items: list[ProcedureSummaryOutput]
    next_cursor: str | None


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="list_procedures",
        description=(
            "List procedures, newest first. Give a name to find the routines "
            "composed under it, or give none to see everything this system knows "
            "how to run. A row carries how many steps the routine has; read the "
            "steps themselves with get_procedure. Pass the next_cursor from a "
            "response to read the next page."
        ),
    )
    async def list_procedures_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        name: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> ListProceduresOutput:
        handler = get_handler()
        page = await handler(
            ListProcedures.with_name(name=name, limit=limit, cursor=cursor),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return ListProceduresOutput(
            items=[
                ProcedureSummaryOutput(
                    procedure_id=summary.procedure_id,
                    name=summary.name.value,
                    beamline=summary.beamline.value,
                    step_count=summary.step_count,
                    created_at=summary.created_at,
                )
                for summary in page.items
            ],
            next_cursor=page.next_cursor,
        )
