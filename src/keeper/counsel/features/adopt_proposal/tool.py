"""MCP door for adopting a proposal.

The same handler the HTTP route uses. The handler is fetched per call
rather than at registration, so it sees the bundle the lifespan wired
rather than whatever existed when the server was built.

This is the tool that closes the loop an agent can drive end to end.
Reading an execution, putting a question, answering it with a proposal
and adopting that proposal are now four tools in two contexts, and the
last of them is the only one that commits a beamline to anything.

The beamline and the devices are arguments rather than anything this
derives, and an agent is expected to have read them off the execution
the proposal came from. Offering them is the caller's job; deciding them
is nobody's business but whoever holds the beam time.

No idempotency key. MCP has no client-supplied retry tag to carry one,
so the wrapped handler is called with None and behaves as the bare one.
"""

from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.counsel.features.adopt_proposal.command import AdoptProposal
from keeper.counsel.features.adopt_proposal.handler import IdempotentHandler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class AdoptProposalOutput(BaseModel):
    """What the tool hands back.

    The execution, because that is what the adoption created and what a
    caller watches next. The proposal id it was given rides along, since
    a tool result of one bare id reads as ambiguous to a caller holding
    both.
    """

    proposal_id: UUID
    execution_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], IdempotentHandler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="adopt_proposal",
        description=(
            "Adopt an open proposal: compose a one-step procedure that runs the operation "
            "it proposes, at the named beamline, over the devices given as scopes, and "
            "dispatch it. Returns the execution, which something will then walk. "
            "Refused if the proposal is no longer open."
        ),
    )
    async def adopt_proposal_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        proposal_id: UUID,
        beamline: str,
        scopes: Sequence[str],
    ) -> AdoptProposalOutput:
        handler = get_handler()
        execution_id = await handler(
            AdoptProposal(
                proposal_id=proposal_id,
                beamline=beamline,
                scopes=tuple(scopes),
            ),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return AdoptProposalOutput(proposal_id=proposal_id, execution_id=execution_id)
