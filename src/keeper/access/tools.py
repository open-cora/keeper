"""Register the Access MCP tools on the shared server.

`get_handlers` is called per tool call, not at registration, so a tool
always reaches the bundle the lifespan wired rather than one captured
before startup finished.
"""

from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from keeper.access.features.deactivate_actor import tool as deactivate_actor_tool
from keeper.access.features.get_actor import tool as get_actor_tool
from keeper.access.features.reactivate_actor import tool as reactivate_actor_tool
from keeper.access.features.register_actor import tool as register_actor_tool
from keeper.access.wire import AccessHandlers


def register_access_tools(
    mcp: FastMCP,
    *,
    get_handlers: Callable[[], AccessHandlers],
) -> None:
    """Register every Access slice's MCP tool."""
    register_actor_tool.register(
        mcp,
        get_handler=lambda: get_handlers().register_actor,
    )
    deactivate_actor_tool.register(
        mcp,
        get_handler=lambda: get_handlers().deactivate_actor,
    )
    reactivate_actor_tool.register(
        mcp,
        get_handler=lambda: get_handlers().reactivate_actor,
    )
    get_actor_tool.register(
        mcp,
        get_handler=lambda: get_handlers().get_actor,
    )


__all__ = ["register_access_tools"]
