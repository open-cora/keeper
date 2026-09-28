"""MCP door for listing pursuits.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

The description names both filters and what each is for, because an agent
reading this list has two genuinely different reasons to call it: finding
the pursuit it is acting inside, and finding out whether anything is
already authorized at a beamline before asking for more.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, Field

from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id
from keeper.pursuit.aggregates.pursuit import PursuitStatus, RoundOutcome
from keeper.pursuit.features.list_pursuits.handler import Handler
from keeper.pursuit.features.list_pursuits.query import DEFAULT_PAGE_SIZE, ListPursuits


class PursuitSummaryOutput(BaseModel):
    """One pursuit, as a page shows it."""

    pursuit_id: UUID
    actor_id: UUID
    goal: str
    beamline: str
    status: PursuitStatus
    held_for: RoundOutcome | None = None
    round_count: int
    created_at: str
    stopped_at: str | None = None


class ListPursuitsOutput(BaseModel):
    """What the tool hands back."""

    items: list[PursuitSummaryOutput]
    next_cursor: str | None = Field(
        default=None, description="Pass back as cursor. Absent on the last page."
    )


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="list_pursuits",
        description=(
            "Find pursuits, newest first. Narrow by status to see which loops "
            "are Running, Held or Stopped, and by beamline to see what is "
            "authorized to dispatch work at one. Held pursuits are waiting "
            "for a person, and each says whether a thinker referred it or "
            "simply had nothing to go on."
        ),
    )
    async def list_pursuits_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        status: PursuitStatus | None = None,
        beamline: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> ListPursuitsOutput:
        handler = get_handler()
        page = await handler(
            ListPursuits(status=status, beamline=beamline, limit=limit, cursor=cursor),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return ListPursuitsOutput(
            items=[
                PursuitSummaryOutput(
                    pursuit_id=summary.pursuit_id,
                    actor_id=summary.actor_id,
                    goal=summary.goal,
                    beamline=summary.beamline,
                    status=summary.status,
                    held_for=summary.held_for,
                    round_count=summary.round_count,
                    created_at=summary.created_at.isoformat(),
                    stopped_at=(
                        None if summary.stopped_at is None else summary.stopped_at.isoformat()
                    ),
                )
                for summary in page.items
            ],
            next_cursor=page.next_cursor,
        )
