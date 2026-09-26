"""MCP door for finding inquiries.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

The tool a thinker that goes looking for work calls, with `status` set to
Open. It is also how an operator finds the questions something claimed and
never came back to, with `status` set to Claimed.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.counsel.aggregates.inquiry import InquiryConclusion, InquiryStatus
from keeper.counsel.features.list_inquiries.handler import Handler
from keeper.counsel.features.list_inquiries.query import DEFAULT_PAGE_SIZE, ListInquiries
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class InquirySummaryOutput(BaseModel):
    """An inquiry as a list shows it."""

    inquiry_id: UUID
    actor_id: UUID
    execution_id: UUID
    objective: str
    execution_step_count: int
    status: InquiryStatus
    conclusion: InquiryConclusion | None
    observed_step_count: int | None
    execution_ended: bool | None
    proposal_id: UUID | None
    created_at: datetime
    claimed_at: datetime | None
    answered_at: datetime | None


class ListInquiriesOutput(BaseModel):
    """One page of inquiries, and how to ask for the next."""

    items: list[InquirySummaryOutput]
    next_cursor: str | None


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="list_inquiries",
        description=(
            "Find inquiries, newest first. Status Open is a question nothing has "
            "taken up, Claimed is one something said it was thinking about, and "
            "Answered is one a thinker came back to. Nothing expires a claim, so a "
            "stale Claimed row is how an abandoned thinker shows up."
        ),
    )
    async def list_inquiries_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        status: InquiryStatus | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> ListInquiriesOutput:
        handler = get_handler()
        page = await handler(
            ListInquiries(status=status, limit=limit, cursor=cursor),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return ListInquiriesOutput(
            items=[
                InquirySummaryOutput(
                    inquiry_id=summary.inquiry_id,
                    actor_id=summary.actor_id,
                    execution_id=summary.execution_id,
                    objective=summary.objective,
                    execution_step_count=summary.execution_step_count,
                    status=summary.status,
                    conclusion=summary.conclusion,
                    observed_step_count=summary.observed_step_count,
                    execution_ended=summary.execution_ended,
                    proposal_id=summary.proposal_id,
                    created_at=summary.created_at,
                    claimed_at=summary.claimed_at,
                    answered_at=summary.answered_at,
                )
                for summary in page.items
            ],
            next_cursor=page.next_cursor,
        )
