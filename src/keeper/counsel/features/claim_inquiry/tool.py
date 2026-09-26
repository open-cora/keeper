"""MCP door for claiming an inquiry.

The same handler the HTTP route uses. The handler is fetched per call
rather than at registration, so it sees the bundle the lifespan wired
rather than whatever existed when the server was built.

The tool a thinker that went looking for work calls. One that was handed
its question skips it and answers straight from open.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.counsel.features.claim_inquiry.command import ClaimInquiry
from keeper.counsel.features.claim_inquiry.handler import Handler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class ClaimInquiryOutput(BaseModel):
    """What the tool hands back.

    The id it was given, because a tool result of nothing reads as a
    failure to a caller that cannot see a 204.
    """

    inquiry_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="claim_inquiry",
        description=(
            "Say that this thinker has taken an open inquiry up. Refused if the "
            "inquiry is already claimed or already answered. Claiming is optional: "
            "an inquiry can be answered without one."
        ),
    )
    async def claim_inquiry_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        inquiry_id: UUID,
        occurred_at: datetime | None = None,
    ) -> ClaimInquiryOutput:
        handler = get_handler()
        await handler(
            ClaimInquiry(inquiry_id=inquiry_id, occurred_at=occurred_at),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return ClaimInquiryOutput(inquiry_id=inquiry_id)
