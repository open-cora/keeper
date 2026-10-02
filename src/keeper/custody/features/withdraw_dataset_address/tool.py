"""MCP door for withdrawing an address from a dataset.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

No idempotency key. MCP has no client-supplied retry tag to carry one,
and a replayed call is refused by the domain in any case.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.custody.features.withdraw_dataset_address.command import WithdrawDatasetAddress
from keeper.custody.features.withdraw_dataset_address.handler import Handler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id
from keeper.shared.identifier import Identifier


class WithdrawDatasetAddressOutput(BaseModel):
    """What the tool hands back.

    The dataset it was given, because a tool result of nothing reads as
    a failure to a caller that cannot see a 204.
    """

    dataset_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="withdraw_dataset_address",
        description=(
            "Record that this dataset's data is no longer readable at an address, "
            "after something else purged or moved it. This does not delete data. "
            "Refused if the dataset is not recorded at that address."
        ),
    )
    async def withdraw_dataset_address_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        dataset_id: UUID,
        external_ref_scheme: str,
        external_ref_value: str,
        occurred_at: datetime | None = None,
    ) -> WithdrawDatasetAddressOutput:
        handler = get_handler()
        await handler(
            WithdrawDatasetAddress(
                dataset_id=dataset_id,
                external_ref=Identifier(scheme=external_ref_scheme, value=external_ref_value),
                occurred_at=occurred_at,
            ),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return WithdrawDatasetAddressOutput(dataset_id=dataset_id)
