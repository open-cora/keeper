"""MCP door for resuming a pursuit.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

This one is reachable by the same kind of caller a pursuit authorizes, and
unlike withdrawing it is not the safe direction: resuming puts a loop that
stopped asking back to work.

It is here all the same. A referral only a person could clear would mean a
beamline waits for somebody to be awake, and the check that matters is
Authority's rather than which door the call came through. What a resume
cannot do is widen anything. The goal, the beamline, the scopes and the
budget are what they were, and a pursuit resumed with nothing left in its
budget is refused at the next round it tries to open.

No idempotency key, and this handler is not wrapped in one. A replayed
resume is refused, beside every other transition in this tree.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id
from keeper.pursuit.features.resume_pursuit.command import ResumePursuit
from keeper.pursuit.features.resume_pursuit.handler import Handler


class ResumePursuitOutput(BaseModel):
    """What the tool hands back.

    A field rather than nothing, because a tool returning an empty object
    reads to a client as a call that may not have done anything. The id is
    what the caller already sent, echoed so the answer names its subject.
    """

    pursuit_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="resume_pursuit",
        description=(
            "Put a held pursuit back to work, so it can open rounds again. A "
            "pursuit holds when a thinker had nothing to go on or asked for a "
            "person. Nothing about the authorization changes: the goal, "
            "beamline, scopes and budget are what they were. Refused if the "
            "pursuit is already running or has stopped."
        ),
    )
    async def resume_pursuit_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        pursuit_id: UUID,
    ) -> ResumePursuitOutput:
        handler = get_handler()
        await handler(
            ResumePursuit(pursuit_id=pursuit_id),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return ResumePursuitOutput(pursuit_id=pursuit_id)
