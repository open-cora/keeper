"""MCP door for registering a description of a dataset.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

The reference arrives as two flat arguments here where the route nests
it, because a tool signature is what a model reads and a nested object
is a schema it has to assemble.

The entries do not get that treatment, and the asymmetry is the point.
A reference is two strings that happen to travel together, so
flattening costs a rule stated in one more place. A list of entries is
a list, and flattening it would mean parallel arrays of paths, roles
and shapes that a caller has to keep aligned by position. Three lists
that must stay the same length is a shape a writer gets wrong, and it
would get wrong silently.

No idempotency key. MCP has no client-supplied retry tag to carry one,
and a repeated description is refused by the domain in any case.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, Field

from keeper.custody.aggregates.dataset import (
    ENTRY_PATH_MAX_LENGTH,
    MANIFEST_LABEL_MAX_LENGTH,
    MANIFEST_MAX_ENTRIES,
    Entry,
    Extent,
    Manifest,
)
from keeper.custody.features.register_dataset_manifest.command import RegisterDatasetManifest
from keeper.custody.features.register_dataset_manifest.handler import Handler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id
from keeper.shared.identifier import Identifier


class EntryInput(BaseModel):
    """One thing inside the container, as a caller describes it.

    `shape` is the dimensions of an array when `dtype` is given, and a
    single count of what a region holds when it is not. `capacity` is
    what the container reserved, where it says so, and it has as many
    numbers as the shape.

    There is no field for a value read out of the data, and that is the
    rule this whole description exists under: enough to decide whether
    to open the data, never enough to answer instead of opening it.
    """

    path: str = Field(min_length=1, max_length=ENTRY_PATH_MAX_LENGTH)
    shape: list[int] | None = None
    capacity: list[int] | None = None
    dtype: str | None = Field(default=None, max_length=MANIFEST_LABEL_MAX_LENGTH)
    role: str | None = Field(default=None, max_length=MANIFEST_LABEL_MAX_LENGTH)


class RegisterDatasetManifestOutput(BaseModel):
    """What the tool hands back.

    The dataset it was given, because a tool result of nothing reads as
    a failure to a caller that cannot see a 204.
    """

    dataset_id: UUID


def _entry(given: EntryInput) -> Entry:
    extent = (
        None
        if given.shape is None
        else Extent(
            shape=tuple(given.shape),
            capacity=None if given.capacity is None else tuple(given.capacity),
            dtype=given.dtype,
        )
    )
    return Entry(path=given.path, extent=extent, role=given.role)


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="register_dataset_manifest",
        description=(
            "Record what is inside one copy of a dataset, after something opened it "
            "and looked. Give the address of the copy that was opened, the convention "
            "its names follow, and one entry per thing worth naming. Report what is "
            "there and never what a convention says should be there: a missing entry "
            "is the most useful thing this can carry. Entries hold structure only, so "
            "there is nowhere to put a value read out of the data. Refused if the "
            "dataset is not recorded at that address, or if the description repeats "
            "what the record already says."
        ),
    )
    async def register_dataset_manifest_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        dataset_id: UUID,
        external_ref_scheme: str,
        external_ref_value: str,
        convention: str,
        entries: Annotated[list[EntryInput], Field(max_length=MANIFEST_MAX_ENTRIES)],
        occurred_at: datetime | None = None,
    ) -> RegisterDatasetManifestOutput:
        handler = get_handler()
        await handler(
            RegisterDatasetManifest(
                dataset_id=dataset_id,
                external_ref=Identifier(scheme=external_ref_scheme, value=external_ref_value),
                manifest=Manifest(
                    convention=convention,
                    entries=tuple(_entry(given) for given in entries),
                ),
                occurred_at=occurred_at,
            ),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return RegisterDatasetManifestOutput(dataset_id=dataset_id)
