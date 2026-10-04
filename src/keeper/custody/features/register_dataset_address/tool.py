"""MCP door for registering another address for a dataset.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

The reference and the citation arrive as flat arguments here where the
route nests them, because a tool signature is what a model reads and a
nested object in one is a schema it has to assemble. The halves are
rebuilt into value objects before the command is built, so the same
pairing rule holds on both surfaces; what differs is only where it is
enforced.

No idempotency key. MCP has no client-supplied retry tag to carry one,
and a replayed call is refused by the domain in any case.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.custody.aggregates.dataset import CopiedBy
from keeper.custody.features.register_dataset_address.command import RegisterDatasetAddress
from keeper.custody.features.register_dataset_address.handler import Handler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id
from keeper.shared.identifier import Identifier


class HalfACitationError(ValueError):
    """One half of a citation arrived without the other.

    The route cannot reach this, because its body nests the two and a
    nested object is whole or absent. A flat tool signature can express
    the half, so the rule is stated here instead, and it is the same
    rule: a citation names the work that made the copy, and one id
    names nothing.
    """

    def __init__(self) -> None:
        super().__init__(
            "copied_by_execution_id and copied_by_step_id are given together or not at all"
        )


class RegisterDatasetAddressOutput(BaseModel):
    """What the tool hands back.

    The dataset it was given, because a tool result of nothing reads as
    a failure to a caller that cannot see a 204.
    """

    dataset_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="register_dataset_address",
        description=(
            "Record another place this dataset's data can be read, after something "
            "else copied or published it. This does not move data. Give "
            "copied_by_execution_id and copied_by_step_id only when this system "
            "dispatched the work that made the copy. Refused if the dataset is "
            "already recorded at that address."
        ),
    )
    async def register_dataset_address_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        dataset_id: UUID,
        external_ref_scheme: str,
        external_ref_value: str,
        copied_by_execution_id: UUID | None = None,
        copied_by_step_id: UUID | None = None,
        occurred_at: datetime | None = None,
    ) -> RegisterDatasetAddressOutput:
        if (copied_by_execution_id is None) != (copied_by_step_id is None):
            raise HalfACitationError
        handler = get_handler()
        await handler(
            RegisterDatasetAddress(
                dataset_id=dataset_id,
                external_ref=Identifier(scheme=external_ref_scheme, value=external_ref_value),
                copied_by=(
                    None
                    if copied_by_execution_id is None or copied_by_step_id is None
                    else CopiedBy(execution_id=copied_by_execution_id, step_id=copied_by_step_id)
                ),
                occurred_at=occurred_at,
            ),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return RegisterDatasetAddressOutput(dataset_id=dataset_id)
