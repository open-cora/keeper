"""MCP door for withdrawing a pursuit.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

This tool is reachable by the same kind of caller a pursuit authorizes,
which is worth a thought and is fine. Stopping is the safe direction: an
agent that withdraws a pursuit it should not have has removed a permission
and can be given another, and one that cannot stop a loop it can see going
wrong is worse than one that can.

No idempotency key, and this handler is not wrapped in one either. A
replayed withdrawal is refused, beside every other transition in this
tree, and `wire.py` holds the reason it is not the exception it was first
written as.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id
from keeper.pursuit.features.withdraw_pursuit.command import WithdrawPursuit
from keeper.pursuit.features.withdraw_pursuit.handler import Handler


class WithdrawPursuitOutput(BaseModel):
    """What the tool hands back.

    A field rather than nothing, because a tool returning an empty object
    reads to a client as a call that may not have done anything. The id is
    what the caller already sent, echoed so the answer names its subject.
    """

    pursuit_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="withdraw_pursuit",
        description=(
            "Stop a pursuit authorizing anything further. Work already "
            "dispatched keeps running and the record of it is unchanged; "
            "what ends is the permission to dispatch more. Refused if the "
            "pursuit has already stopped."
        ),
    )
    async def withdraw_pursuit_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        pursuit_id: UUID,
    ) -> WithdrawPursuitOutput:
        handler = get_handler()
        await handler(
            WithdrawPursuit(pursuit_id=pursuit_id),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return WithdrawPursuitOutput(pursuit_id=pursuit_id)
