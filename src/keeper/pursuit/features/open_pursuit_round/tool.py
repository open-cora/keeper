"""MCP door for opening a round of a pursuit.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

The description says what the caller gets back and what to do with it,
because this is the tool that starts a turn of the loop and the inquiry it
returns is the handle for everything that follows.

No idempotency key. MCP has no client-supplied retry tag to carry one, and
none is wanted: a second round about one execution is refused by the
pursuit itself.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id
from keeper.pursuit.features.open_pursuit_round.command import OpenPursuitRound
from keeper.pursuit.features.open_pursuit_round.handler import Handler


class OpenPursuitRoundOutput(BaseModel):
    """What the tool hands back."""

    pursuit_id: UUID
    inquiry_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="open_pursuit_round",
        description=(
            "Turn a pursuit once by asking what should run next, given one "
            "execution. The question is the pursuit's own goal, so there is "
            "nothing to phrase. Returns the inquiry a thinker should claim "
            "and answer. Refused if the pursuit has stopped, has spent a "
            "budget dimension, or has already asked about that execution."
        ),
    )
    async def open_pursuit_round_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        pursuit_id: UUID,
        execution_id: UUID,
    ) -> OpenPursuitRoundOutput:
        handler = get_handler()
        inquiry_id = await handler(
            OpenPursuitRound(pursuit_id=pursuit_id, execution_id=execution_id),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return OpenPursuitRoundOutput(pursuit_id=pursuit_id, inquiry_id=inquiry_id)
