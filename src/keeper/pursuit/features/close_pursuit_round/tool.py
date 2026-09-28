"""MCP door for closing a round of a pursuit.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

The description spells out all four outcomes, because this is the call
that decides whether a loop keeps turning and an agent driving one needs
to know what each answer means before it gets one.

No idempotency key, and none is wanted: a round that has already closed is
refused by the pursuit itself, so a retry gets a conflict rather than a
second dispatch.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id
from keeper.pursuit.aggregates.pursuit import RoundOutcome
from keeper.pursuit.features.close_pursuit_round.command import ClosePursuitRound
from keeper.pursuit.features.close_pursuit_round.handler import Handler


class ClosePursuitRoundOutput(BaseModel):
    """What the tool hands back."""

    pursuit_id: UUID
    round_index: int
    outcome: RoundOutcome
    dispatched_id: UUID | None = None


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="close_pursuit_round",
        description=(
            "Read the answer to a round and act on it. There is nothing to "
            "pass but the round: the conclusion is already on its inquiry. "
            "Propose adopts the proposal at the pursuit's own beamline and "
            "scopes and returns the execution it dispatched. Stop ends the "
            "pursuit. Abstain and Refer both hold it until a person resumes "
            "it. Refused if the inquiry has not been answered yet."
        ),
    )
    async def close_pursuit_round_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        pursuit_id: UUID,
        round_index: int,
    ) -> ClosePursuitRoundOutput:
        handler = get_handler()
        closed = await handler(
            ClosePursuitRound(pursuit_id=pursuit_id, round_index=round_index),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return ClosePursuitRoundOutput(
            pursuit_id=pursuit_id,
            round_index=round_index,
            outcome=closed.outcome,
            dispatched_id=closed.dispatched_id,
        )
