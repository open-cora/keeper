"""MCP door for registering a dataset.

The same handler the HTTP route uses. The handler is fetched per call
rather than at registration, so it sees the bundle the lifespan wired
rather than whatever existed when the server was built.

The reference pair arrives as two flat arguments here, where the route
takes a nested object. A tool's arguments are a flat keyword list, and
nesting one object inside it would buy shape at the cost of every client
having to construct it. Both doors build the same value object before the
command exists, which is where the shape actually matters.

No idempotency key. MCP has no client-supplied retry tag to carry one, so
the wrapped handler is called with None and behaves as the bare one.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.custody.features.register_dataset.command import RegisterDataset
from keeper.custody.features.register_dataset.handler import IdempotentHandler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id
from keeper.shared.identifier import Identifier


class RegisterDatasetOutput(BaseModel):
    """What the tool hands back."""

    dataset_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], IdempotentHandler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="register_dataset",
        description=(
            "Record where an acquisition's output data ended up: the execution "
            "and step that produced it, and the store's own address for the data."
        ),
    )
    async def register_dataset_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        execution_id: UUID,
        step_id: UUID,
        external_ref_scheme: str,
        external_ref_value: str,
        occurred_at: datetime | None = None,
    ) -> RegisterDatasetOutput:
        handler = get_handler()
        dataset_id = await handler(
            RegisterDataset(
                execution_id=execution_id,
                step_id=step_id,
                external_ref=Identifier(scheme=external_ref_scheme, value=external_ref_value),
                occurred_at=occurred_at,
            ),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return RegisterDatasetOutput(dataset_id=dataset_id)
