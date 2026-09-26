"""MCP door for making an inquiry.

The same handler the HTTP route uses. The handler is fetched per call
rather than at registration, so it sees the bundle the lifespan wired
rather than whatever existed when the server was built.

This is the tool the aggregate was built for. A thinker reading an
execution over MCP and recording its question over MCP never touches the
HTTP surface, and the asker on the record is whichever principal the MCP
request authenticated as.

No idempotency key. MCP has no client-supplied retry tag to carry one, so
the wrapped handler is called with None and behaves as the bare one.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.counsel.features.make_inquiry.command import MakeInquiry
from keeper.counsel.features.make_inquiry.handler import IdempotentHandler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class MakeInquiryOutput(BaseModel):
    """What the tool hands back."""

    inquiry_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], IdempotentHandler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="make_inquiry",
        description=(
            "Put a question to a thinker about one execution: which execution, and what "
            "the asker wants to know. Records the asking, and thinks nothing."
        ),
    )
    async def make_inquiry_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        execution_id: UUID,
        objective: str,
    ) -> MakeInquiryOutput:
        handler = get_handler()
        inquiry_id = await handler(
            MakeInquiry(execution_id=execution_id, objective=objective),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return MakeInquiryOutput(inquiry_id=inquiry_id)
