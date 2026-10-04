"""MCP door for reading a dataset.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

The reference comes back as two flat fields, matching the way the
registering tool takes them.

The description comes back nested, matching the way the describing tool
takes it, and for the same reason: a list of entries cannot be
flattened without parallel arrays a reader has to align by position.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.custody.aggregates.dataset import Description
from keeper.custody.features.get_dataset.handler import Handler
from keeper.custody.features.get_dataset.query import GetDataset
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class ExternalRefOutput(BaseModel):
    """One store's address for this data.

    A nested object rather than two flat fields, now that a dataset can
    be at several addresses at once. Flattening would need an index in
    every name and would let a caller build half a reference.
    """

    scheme: str
    value: str


class ExtentOutput(BaseModel):
    """How much of something there is, and of what.

    With a `dtype` the shape is an array's dimensions. Without one it
    is a single count of what a region holds.
    """

    shape: list[int]
    capacity: list[int] | None
    dtype: str | None


class EntryOutput(BaseModel):
    """One thing inside the data, and what a convention calls it.

    What is absent here matters as much as what is present. An entry a
    convention expects and this does not list was not in the container
    when somebody looked, and for a tomography scan a complete set of
    frames with no rotation angles beside them cannot be reconstructed.
    """

    path: str
    extent: ExtentOutput | None
    role: str | None


class DescriptionOutput(BaseModel):
    """What was inside one copy of the data when somebody looked.

    As of `described_at`, and of the copy named by `external_ref`. It
    is not refreshed and does not claim to be current, so a caller
    deciding something expensive on it should weigh how old it is.
    """

    external_ref: ExternalRefOutput
    convention: str
    entries: list[EntryOutput]
    described_at: datetime


class GetDatasetOutput(BaseModel):
    """A dataset as this system currently holds it."""

    dataset_id: UUID
    execution_id: UUID
    step_id: UUID
    external_refs: list[ExternalRefOutput]
    description: DescriptionOutput | None


def _described(description: Description | None) -> DescriptionOutput | None:
    if description is None:
        return None
    return DescriptionOutput(
        external_ref=ExternalRefOutput(
            scheme=description.external_ref.scheme, value=description.external_ref.value
        ),
        convention=description.manifest.convention,
        entries=[
            EntryOutput(
                path=entry.path,
                extent=None
                if entry.extent is None
                else ExtentOutput(
                    shape=list(entry.extent.shape),
                    capacity=None if entry.extent.capacity is None else list(entry.extent.capacity),
                    dtype=entry.extent.dtype,
                ),
                role=entry.role,
            )
            for entry in description.manifest.entries
        ],
        described_at=description.described_at,
    )


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="get_dataset",
        description=(
            "Read a dataset by id: the run that produced the data, the store's address "
            "for it, and what was inside when somebody last looked. The description is "
            "as of when it was taken, and null when nobody has described the data."
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
            external_refs=[
                ExternalRefOutput(scheme=ref.scheme, value=ref.value)
                for ref in dataset.external_refs
            ],
            description=_described(dataset.description),
        )
