"""MCP door for making a proposal.

The same handler the HTTP route uses. The handler is fetched per call
rather than at registration, so it sees the bundle the lifespan wired
rather than whatever existed when the server was built.

This is the tool the context was built for. An agent reading plans over
MCP and putting a run forward over MCP never touches the HTTP surface,
and the proposer on the record is whichever principal the MCP request
authenticated as.

No idempotency key. MCP has no client-supplied retry tag to carry one,
so the wrapped handler is called with None and behaves as the bare one.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.counsel.features.make_proposal.command import MakeProposal
from keeper.counsel.features.make_proposal.handler import IdempotentHandler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class MakeProposalOutput(BaseModel):
    """What the tool hands back."""

    proposal_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], IdempotentHandler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="make_proposal",
        description=(
            "Put a run forward: the plan to run, and the values to run it with. "
            "Records what was proposed, and runs nothing."
        ),
    )
    async def make_proposal_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        plan_id: UUID,
        parameters: dict[str, Any] | None = None,
    ) -> MakeProposalOutput:
        handler = get_handler()
        proposal_id = await handler(
            MakeProposal(plan_id=plan_id, parameters=parameters if parameters is not None else {}),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return MakeProposalOutput(proposal_id=proposal_id)
