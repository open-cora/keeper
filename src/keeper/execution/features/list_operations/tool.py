"""MCP door for listing operations.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

The description says out loud that a name can match more than one operation,
because a model that assumes otherwise will take the first row and report
a definite answer it does not have.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.execution.features.list_operations.handler import Handler
from keeper.execution.features.list_operations.query import DEFAULT_PAGE_SIZE, ListOperations
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class OperationSummaryOutput(BaseModel):
    """One operation, as a list shows it.

    No schema: a page of them is mostly schema, and `get_operation` has it.
    """

    operation_id: UUID
    name: str
    created_at: datetime


class ListOperationsOutput(BaseModel):
    """A page of operations, and how to ask for the next one."""

    items: list[OperationSummaryOutput]
    next_cursor: str | None


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="list_operations",
        description=(
            "List operations, newest first. Give a name to find the operations written down "
            "under it, or give none to see what can be run. A name may match more "
            "than one operation, because one routine constrained two ways is two operations; "
            "read the schema of each with get_operation before choosing. Pass the "
            "next_cursor from a response to read the next page."
        ),
    )
    async def list_operations_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        name: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> ListOperationsOutput:
        handler = get_handler()
        page = await handler(
            ListOperations.with_name(name=name, limit=limit, cursor=cursor),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return ListOperationsOutput(
            items=[
                OperationSummaryOutput(
                    operation_id=summary.operation_id,
                    name=summary.name.value,
                    created_at=summary.created_at,
                )
                for summary in page.items
            ],
            next_cursor=page.next_cursor,
        )
