"""MCP door for finding proposals.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

This is the tool that makes the loop observable from the agent side. An
agent that has been proposing all afternoon asks which of its advice
nobody took, and an operator asks the same question about the whole
deployment, through the same call.

`is_open` defaults to None here rather than to True. A tool argument
with a helpful default is a tool that quietly answers a narrower question
than it was asked, and a caller wanting the open ones can say so.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.counsel.features.list_proposals.handler import Handler
from keeper.counsel.features.list_proposals.query import (
    DEFAULT_PAGE_SIZE,
    ListProposals,
)
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class ProposalSummaryOutput(BaseModel):
    """A proposal as a list shows it."""

    proposal_id: UUID
    actor_id: UUID
    plan_id: UUID
    execution_id: UUID | None
    step_id: UUID | None
    created_at: datetime
    taken_at: datetime | None


class ListProposalsOutput(BaseModel):
    """One page of proposals, and how to ask for the next."""

    items: list[ProposalSummaryOutput]
    next_cursor: str | None


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="list_proposals",
        description=(
            "Find proposals, newest first. Pass is_open true for the ones no run "
            "has taken, false for the ones a run did, and omit it for all of them."
        ),
    )
    async def list_proposals_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        is_open: bool | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> ListProposalsOutput:
        handler = get_handler()
        page = await handler(
            ListProposals(is_open=is_open, limit=limit, cursor=cursor),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return ListProposalsOutput(
            items=[
                ProposalSummaryOutput(
                    proposal_id=summary.proposal_id,
                    actor_id=summary.actor_id,
                    plan_id=summary.plan_id,
                    execution_id=summary.execution_id,
                    step_id=summary.step_id,
                    created_at=summary.created_at,
                    taken_at=summary.taken_at,
                )
                for summary in page.items
            ],
            next_cursor=page.next_cursor,
        )
