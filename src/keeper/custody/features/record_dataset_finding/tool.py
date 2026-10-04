"""MCP door for recording a finding about a dataset.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

The arguments are the same three the route takes, because they were
already flat there. The manifest beside this one has to flatten a
reference and keep a list nested; there is nothing here to make that
choice about.

No idempotency key. MCP has no client-supplied retry tag to carry one,
and a repeated finding is refused by the domain in any case.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, Field

from keeper.custody.aggregates.dataset import FINDING_JUDGEMENT_MAX_LENGTH, Finding
from keeper.custody.features.record_dataset_finding.command import RecordDatasetFinding
from keeper.custody.features.record_dataset_finding.handler import Handler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class RecordDatasetFindingOutput(BaseModel):
    """What the tool hands back.

    The dataset it was given, because a tool result of nothing reads as
    a failure to a caller that cannot see a 204.
    """

    dataset_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="record_dataset_finding",
        description=(
            "Record what you concluded about a dataset, after comparing what was "
            "asked for against what the record says arrived. Give one short word for "
            "the judgement, naming both what you examined and your verdict on it, "
            "and the two counts you weighed. Presence is a count: a thing that should "
            "be there and is not is one against zero. There is nowhere to put a value "
            "read out of the data, and nowhere to put your reasoning. Refused if the "
            "dataset already carries that same finding."
        ),
    )
    async def record_dataset_finding_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        dataset_id: UUID,
        judgement: Annotated[str, Field(max_length=FINDING_JUDGEMENT_MAX_LENGTH)],
        expected: Annotated[int, Field(ge=0)],
        arrived: Annotated[int, Field(ge=0)],
        occurred_at: datetime | None = None,
    ) -> RecordDatasetFindingOutput:
        handler = get_handler()
        await handler(
            RecordDatasetFinding(
                dataset_id=dataset_id,
                finding=Finding(judgement=judgement, expected=expected, arrived=arrived),
                occurred_at=occurred_at,
            ),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return RecordDatasetFindingOutput(dataset_id=dataset_id)
