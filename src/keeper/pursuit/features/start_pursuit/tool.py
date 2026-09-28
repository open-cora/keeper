"""MCP door for starting a pursuit.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

The budget arrives as a mapping here as it does on the route, because it
is the one argument whose shape is the point: a flat pair of arguments per
dimension would fix the dimension list in the tool signature, and the
whole reason a budget is a mapping is that a deployment picks which
dimensions it bounds.

The description says plainly what starting one means, because an agent
reading this list is exactly the kind of caller that should not discover
by trying. This is the tool that hands a machine a standing permission,
and the one refusal it cannot recover from is a budget it set too high.

No idempotency key. MCP has no client-supplied retry tag to carry one, so
the wrapped handler is called with None and behaves as the bare one.
"""

from collections.abc import Callable, Mapping
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id
from keeper.pursuit.aggregates.pursuit import (
    Budget,
    BudgetDimension,
    PursuitBeamline,
    PursuitGoal,
)
from keeper.pursuit.features.start_pursuit.command import StartPursuit
from keeper.pursuit.features.start_pursuit.handler import IdempotentHandler


class StartPursuitOutput(BaseModel):
    """What the tool hands back."""

    pursuit_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], IdempotentHandler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="start_pursuit",
        description=(
            "Authorize a bounded loop toward a goal: what it is for, which "
            "beamline it runs at, which scopes it may drive, and a budget "
            "keyed by dimension such as Rounds, Executions, WallSeconds, "
            "BeamSeconds or Tokens. Everything acting inside the pursuit is "
            "checked against these, and the budget cannot be raised "
            "afterwards. At least one dimension is required."
        ),
    )
    async def start_pursuit_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        goal: str,
        beamline: str,
        scopes: list[str],
        budget: Mapping[BudgetDimension, int],
    ) -> StartPursuitOutput:
        handler = get_handler()
        pursuit_id = await handler(
            StartPursuit(
                goal=PursuitGoal(goal),
                beamline=PursuitBeamline(beamline),
                scopes=tuple(scopes),
                budget=Budget(dict(budget)),
            ),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return StartPursuitOutput(pursuit_id=pursuit_id)
