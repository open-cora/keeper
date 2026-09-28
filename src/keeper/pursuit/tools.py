"""Register the Pursuit MCP tools on the shared server.

`get_handlers` is called per tool call, not at registration, so a tool
always reaches the bundle the lifespan wired rather than one captured
before startup finished.

All three are here, including the one that hands out a standing
permission, and that is worth stating rather than leaving to be noticed.

An agent can start a pursuit. The alternative would be an HTTP-only
genesis, and it was rejected: a surface a person can reach and an agent
cannot is a surface that gets worked around, and the check that matters is
Authority's rather than which door the call came through. What keeps this
safe is not the door. It is that a budget cannot be raised, a scope cannot
be widened, and every refusal is written down beside the pursuit that
caused it.
"""

from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from keeper.pursuit.features.get_pursuit import tool as get_pursuit_tool
from keeper.pursuit.features.start_pursuit import tool as start_pursuit_tool
from keeper.pursuit.features.withdraw_pursuit import tool as withdraw_pursuit_tool
from keeper.pursuit.wire import PursuitHandlers


def register_pursuit_tools(
    mcp: FastMCP,
    *,
    get_handlers: Callable[[], PursuitHandlers],
) -> None:
    """Register every Pursuit slice's MCP tool."""
    start_pursuit_tool.register(
        mcp,
        get_handler=lambda: get_handlers().start_pursuit,
    )
    withdraw_pursuit_tool.register(
        mcp,
        get_handler=lambda: get_handlers().withdraw_pursuit,
    )
    get_pursuit_tool.register(
        mcp,
        get_handler=lambda: get_handlers().get_pursuit,
    )


__all__ = ["register_pursuit_tools"]
