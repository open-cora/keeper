"""The Access MCP tools, as the registrar actually leaves them.

Every slice here is meant to reach both surfaces. The HTTP half is
covered by the route tests next door; this is the other half, and until
it existed a slice could ship its tool module, never register it, and
pass the whole suite. A planted mutation that deleted one registration
call survived the entire run.

Tools are listed off a server this test builds rather than off the
mounted application, because what is being checked is the registrar: the
mount is a single line in `create_app` and a separate concern.
"""

import pytest
from mcp.server.fastmcp import FastMCP

from keeper.access import register_access_tools
from keeper.access.wire import AccessHandlers

pytestmark = pytest.mark.contract

EXPECTED_ACCESS_TOOLS = frozenset(
    {"register_actor", "deactivate_actor", "reactivate_actor", "get_actor"}
)
"""Every MCP tool the Access bounded context publishes.

One entry per slice, named for the slice directory, reads included. A slice
landing or retiring a tool fails the test below, which is the intent:
the MCP surface should change in a diff rather than drift behind the
HTTP one.
"""


def _unwired() -> AccessHandlers:
    """A bundle that would fail if called.

    Registration must not invoke a handler, so nothing here needs to be
    real. `get_handlers` is called per tool call, not at registration,
    and this stands in to prove it.
    """
    raise AssertionError("registration must not reach for a handler")


async def test_the_registered_tool_names_match_the_pinned_set() -> None:
    mcp = FastMCP("test")
    register_access_tools(mcp, get_handlers=_unwired)

    names = frozenset(tool.name for tool in await mcp.list_tools())

    assert names == EXPECTED_ACCESS_TOOLS, (
        f"Access MCP tools changed.\nAdded: {sorted(names - EXPECTED_ACCESS_TOOLS)}\n"
        f"Removed: {sorted(EXPECTED_ACCESS_TOOLS - names)}\n"
        "Update EXPECTED_ACCESS_TOOLS deliberately when a slice lands or retires a tool."
    )


async def test_every_tool_carries_a_description_and_not_a_bare_name() -> None:
    """A tool with no description is one a model has to guess the use of."""
    mcp = FastMCP("test")
    register_access_tools(mcp, get_handlers=_unwired)

    undescribed = [tool.name for tool in await mcp.list_tools() if not (tool.description or "")]

    assert not undescribed, f"MCP tools with no description: {sorted(undescribed)}"


async def test_registering_the_tools_never_reaches_for_a_handler() -> None:
    """The lazy-lookup contract, asserted rather than trusted.

    `_unwired` raises on call. Registration completing means no tool
    captured a handler at registration time, which is what lets the
    lifespan wire the bundle after the server is built.
    """
    mcp = FastMCP("test")
    register_access_tools(mcp, get_handlers=_unwired)
    assert await mcp.list_tools()
