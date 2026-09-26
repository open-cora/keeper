"""Register the Counsel MCP tools on the shared server.

`get_handlers` is called per tool call, not at registration, so a tool
always reaches the bundle the lifespan wired rather than one captured
before startup finished.

These are the tools an agent actually holds. Reading plans belongs to
Execution and reading an execution back belongs there too, so a full turn
of the loop crosses two contexts' tools and writes only in this one.

The inquiry five are what a thinker calls. `list_inquiries` finds work,
`claim_inquiry` takes it, `answer_inquiry` reports the conclusion, and
`make_inquiry` is what whoever wanted to know calls first. Before they
existed a thinker could only call `make_proposal`, so three of its four
conclusions reached nothing.
"""

from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from keeper.counsel.features.answer_inquiry import tool as answer_inquiry_tool
from keeper.counsel.features.claim_inquiry import tool as claim_inquiry_tool
from keeper.counsel.features.get_inquiry import tool as get_inquiry_tool
from keeper.counsel.features.get_proposal import tool as get_proposal_tool
from keeper.counsel.features.list_inquiries import tool as list_inquiries_tool
from keeper.counsel.features.list_proposals import tool as list_proposals_tool
from keeper.counsel.features.make_inquiry import tool as make_inquiry_tool
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
    make_inquiry_tool.register(
        mcp,
        get_handler=lambda: get_handlers().make_inquiry,
    )
    claim_inquiry_tool.register(
        mcp,
        get_handler=lambda: get_handlers().claim_inquiry,
    )
    answer_inquiry_tool.register(
        mcp,
        get_handler=lambda: get_handlers().answer_inquiry,
    )
    get_inquiry_tool.register(
        mcp,
        get_handler=lambda: get_handlers().get_inquiry,
    )
    list_inquiries_tool.register(
        mcp,
        get_handler=lambda: get_handlers().list_inquiries,
    )


__all__ = ["register_counsel_tools"]
