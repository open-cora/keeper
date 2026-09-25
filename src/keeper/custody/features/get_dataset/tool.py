"""MCP door for reading a dataset.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

The reference comes back as two flat fields, matching the way the
registering tool takes them.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.custody.features.get_dataset.handler import Handler
from keeper.custody.features.get_dataset.query import GetDataset
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class GetDatasetOutput(BaseModel):
    """A dataset as this system currently holds it."""

    dataset_id: UUID
    execution_id: UUID
    step_id: UUID
    external_ref_scheme: str
    external_ref_value: str


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="get_dataset",
        description=(
            "Read a dataset by id: the run that produced the data, and the store's address for it."
        ),
    )
    async def get_dataset_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        dataset_id: UUID,
    ) -> GetDatasetOutput:
        handler = get_handler()
        dataset = await handler(
            GetDataset(dataset_id=dataset_id),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return GetDatasetOutput(
            dataset_id=dataset.id,
            execution_id=dataset.execution_id,
            step_id=dataset.step_id,
            external_ref_scheme=dataset.external_ref.scheme,
            external_ref_value=dataset.external_ref.value,
        )
