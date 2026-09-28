"""MCP door for charging a pursuit.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

This is the tool a thinker calls to charge its own tokens, which is the
whole reason the two reported dimensions exist. It also means the number
is self-reported: a thinker that crashed before calling this got its
tokens free, and a pursuit is a governor rather than an accounting system.

No idempotency key. MCP has no client-supplied retry tag to carry one, so
the wrapped handler is called with None and behaves as the bare one, and a
tool call delivered twice charges twice. A caller that cannot afford that
has the HTTP route, where the key does something.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id
from keeper.pursuit.aggregates.pursuit import BudgetDimension
from keeper.pursuit.features.charge_pursuit.command import ChargePursuit
from keeper.pursuit.features.charge_pursuit.handler import IdempotentHandler


class ChargePursuitOutput(BaseModel):
    """What the tool hands back: where the budget now stands."""

    pursuit_id: UUID
    dimension: BudgetDimension
    total: int


def register(mcp: FastMCP, *, get_handler: Callable[[], IdempotentHandler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="charge_pursuit",
        description=(
            "Report what a pursuit consumed somewhere this system cannot "
            "measure: BeamSeconds or Tokens. The amount is added to what the "
            "pursuit has already spent, not substituted for it, so send what "
            "this turn cost rather than a running total. Refused for any "
            "other dimension, and for one the pursuit was not bounded in."
        ),
    )
    async def charge_pursuit_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        pursuit_id: UUID,
        dimension: BudgetDimension,
        amount: int,
        occurred_at: datetime | None = None,
    ) -> ChargePursuitOutput:
        handler = get_handler()
        total = await handler(
            ChargePursuit(
                pursuit_id=pursuit_id,
                dimension=dimension,
                amount=amount,
                occurred_at=occurred_at,
            ),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return ChargePursuitOutput(pursuit_id=pursuit_id, dimension=dimension, total=total)
