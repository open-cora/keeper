"""MCP door for reading an inquiry.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

`conclusion` comes back null while nothing has answered, which is how an
agent checking on a question it put tells whether a thinker got to it. Set,
it is one of the four words, and `observed_step_count` beside
`execution_step_count` says how much the thinker had seen when it said so.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.counsel.aggregates.inquiry import InquiryConclusion, InquiryStatus
from keeper.counsel.features.get_inquiry.handler import Handler
from keeper.counsel.features.get_inquiry.query import GetInquiry
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class GetInquiryOutput(BaseModel):
    """An inquiry as this system currently holds it."""

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


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="get_inquiry",
        description=(
            "Read an inquiry by id: who asked, about which execution, what they "
            "wanted to know, and what a thinker concluded if one has, beside how "
            "much of the execution it had read when it concluded it."
        ),
    )
    async def get_inquiry_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        inquiry_id: UUID,
    ) -> GetInquiryOutput:
        handler = get_handler()
        inquiry = await handler(
            GetInquiry(inquiry_id=inquiry_id),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return GetInquiryOutput(
            inquiry_id=inquiry.id,
            actor_id=inquiry.actor_id,
            execution_id=inquiry.execution_id,
            objective=inquiry.objective.value,
            execution_step_count=inquiry.execution_step_count,
            status=inquiry.status,
            conclusion=inquiry.conclusion,
            observed_step_count=inquiry.observed_step_count,
            execution_ended=inquiry.execution_ended,
            proposal_id=inquiry.proposal_id,
        )
