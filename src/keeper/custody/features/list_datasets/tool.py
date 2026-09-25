"""MCP door for finding datasets.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

The reference comes back as two flat fields, matching the way the other
two tools in this context spell it.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.custody.features.list_datasets.handler import Handler
from keeper.custody.features.list_datasets.query import DEFAULT_PAGE_SIZE, ListDatasets
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class DatasetSummaryOutput(BaseModel):
    """A dataset as a list shows it."""

    dataset_id: UUID
    execution_id: UUID
    step_id: UUID
    external_ref_scheme: str
    external_ref_value: str
    created_at: datetime


class ListDatasetsOutput(BaseModel):
    """One page, and how to ask for the next."""

    items: list[DatasetSummaryOutput]
    next_cursor: str | None


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="list_datasets",
        description=(
            "Find datasets, newest first. Narrow to one run to see what that "
            "run produced and where it is being kept."
        ),
    )
    async def list_datasets_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        step_id: UUID | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> ListDatasetsOutput:
        handler = get_handler()
        page = await handler(
            ListDatasets(step_id=step_id, limit=limit, cursor=cursor),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return ListDatasetsOutput(
            items=[
                DatasetSummaryOutput(
                    dataset_id=summary.dataset_id,
                    execution_id=summary.execution_id,
                    step_id=summary.step_id,
                    external_ref_scheme=summary.external_ref.scheme,
                    external_ref_value=summary.external_ref.value,
                    created_at=summary.created_at,
                )
                for summary in page.items
            ],
            next_cursor=page.next_cursor,
        )
