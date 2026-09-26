"""MCP door for answering an inquiry.

The same handler the HTTP route uses. The handler is fetched per call
rather than at registration, so it sees the bundle the lifespan wired
rather than whatever existed when the server was built.

This is the tool that gives three of the four conclusions somewhere to go.
Before it, a thinker that concluded anything other than Propose had nothing
to call, so the record only ever heard about the arm that wrote a proposal.

The observation boundary is not optional here either. A thinker that
reports what it concluded without reporting how much it read has recorded a
verdict nobody can weigh.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.counsel.aggregates.inquiry import InquiryConclusion
from keeper.counsel.features.answer_inquiry.command import AnswerInquiry
from keeper.counsel.features.answer_inquiry.handler import Handler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class AnswerInquiryOutput(BaseModel):
    """What the tool hands back.

    The id and the conclusion it recorded, because a tool result of nothing
    reads as a failure to a caller that cannot see a 204.
    """

    inquiry_id: UUID
    conclusion: InquiryConclusion


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="answer_inquiry",
        description=(
            "Record what a thinker concluded about an inquiry: one of Propose, Stop, "
            "Abstain or Refer, how many of the execution's steps it had an outcome for, "
            "and whether the execution had ended when it read. Propose names the "
            "proposal it wrote; the other three name none. Refused if the inquiry "
            "already has an answer."
        ),
    )
    async def answer_inquiry_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        inquiry_id: UUID,
        conclusion: InquiryConclusion,
        observed_step_count: int,
        execution_ended: bool,
        proposal_id: UUID | None = None,
        occurred_at: datetime | None = None,
    ) -> AnswerInquiryOutput:
        handler = get_handler()
        await handler(
            AnswerInquiry(
                inquiry_id=inquiry_id,
                conclusion=conclusion,
                observed_step_count=observed_step_count,
                execution_ended=execution_ended,
                proposal_id=proposal_id,
                occurred_at=occurred_at,
            ),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return AnswerInquiryOutput(inquiry_id=inquiry_id, conclusion=conclusion)
