"""MCP door for recording that an acquisition took a proposal.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

This is the second half of the loop an agent drives over this surface.
It proposed, something ran, and it resolved the acquisition by reading
back the execution that held it; this is where it says so.

No idempotency key. MCP has no client-supplied retry tag to carry one,
and a replayed take is refused by the domain in any case.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.counsel.features.take_proposal.command import TakeProposal
from keeper.counsel.features.take_proposal.handler import Handler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class TakeProposalOutput(BaseModel):
    """What the tool hands back.

    The ids it was given, because a tool result of nothing reads as a
    failure to a caller that cannot see a 204.
    """

    proposal_id: UUID
    execution_id: UUID
    step_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="take_proposal",
        description=(
            "Record that an acquisition step was performed against a proposal. "
            "Refused if the proposal already has one, or if that step ran a "
            "different plan or no plan at all."
        ),
    )
    async def take_proposal_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        proposal_id: UUID,
        execution_id: UUID,
        step_id: UUID,
        occurred_at: datetime | None = None,
    ) -> TakeProposalOutput:
        handler = get_handler()
        await handler(
            TakeProposal(
                proposal_id=proposal_id,
                execution_id=execution_id,
                step_id=step_id,
                occurred_at=occurred_at,
            ),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return TakeProposalOutput(
            proposal_id=proposal_id, execution_id=execution_id, step_id=step_id
        )
