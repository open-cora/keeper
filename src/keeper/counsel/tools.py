"""Register the Counsel MCP tools on the shared server.

`get_handlers` is called per tool call, not at registration, so a tool
always reaches the bundle the lifespan wired rather than one captured
before startup finished.

These three are the ones an agent actually holds. Reading plans belongs
to Execution and resolving a run to its id belongs there too, so a full
turn of the loop crosses two contexts' tools and writes only in this
one.
"""

from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from keeper.counsel.features.get_proposal import tool as get_proposal_tool
from keeper.counsel.features.list_proposals import tool as list_proposals_tool
from keeper.counsel.features.make_proposal import tool as make_proposal_tool
from keeper.counsel.features.take_proposal import tool as take_proposal_tool
from keeper.counsel.wire import CounselHandlers


def register_counsel_tools(
    mcp: FastMCP,
    *,
    get_handlers: Callable[[], CounselHandlers],
) -> None:
    """Register every Counsel slice's MCP tool."""
    make_proposal_tool.register(
        mcp,
        get_handler=lambda: get_handlers().make_proposal,
    )
    get_proposal_tool.register(
        mcp,
        get_handler=lambda: get_handlers().get_proposal,
    )
    take_proposal_tool.register(
        mcp,
        get_handler=lambda: get_handlers().take_proposal,
    )
    list_proposals_tool.register(
        mcp,
        get_handler=lambda: get_handlers().list_proposals,
    )


__all__ = ["register_counsel_tools"]
