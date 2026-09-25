"""An MCP tool takes the caller from the boundary, never from its arguments.

A tool body assembles a handler call out of two kinds of value. Some
were typed by the client and arrive as tool arguments. Three were worked
out about the client and arrive from nowhere the client can reach:

    principal_id    who is calling, resolved from the MCP context
    surface_id      which entrance, a constant for this transport
    correlation_id  the trace this call belongs to

Mixing the two is a whole bug class, and it is not hypothetical. In
`grant_permission/tool.py` the word `principal_id` appears twice, three
lines apart, meaning opposite things: once as the GRANTEE the client
named, once as the CALLER the door established. Writing the first where
the second belongs would let any client act as anyone it can name.

## Why a rule about source and not a test that runs the tools

Because running them cannot see this. Under the test posture the
resolver returns `SYSTEM_PRINCIPAL_ID`, so a tool that hardcoded that
constant would behave identically to one that asked, and a test
asserting the value would agree with either. The contract executions in
`tests/contract/test_mounted_mcp_surface.py` execute every body and are
blind to this on purpose; they check what comes back, and none of these
three ever does.

So the check is on what is written. It ranges over every tool and over
every tool anyone adds, which is the population that matters: these
bodies are written by copying the nearest one, and copying is what keeps
them right until somebody edits instead.

## Scope

MCP tools only. A route reaches the same three values through FastAPI
dependencies, a different shape with its own failure modes, and one rule
stretched over both would check neither precisely.
"""

import ast
from pathlib import Path

import pytest

from tests.architecture.conftest import KEEPER_ROOT, discovered_bcs, tracked_python_files

pytestmark = pytest.mark.architecture

BOUNDARY_RESOLVERS: dict[str, str] = {
    "principal_id": "get_mcp_principal_id",
    "surface_id": "get_mcp_surface_id",
    "correlation_id": "current_correlation_id",
}
"""Handler keyword to the one call allowed to supply it.

A literal is refused even when it would be the right literal today, for
the same reason `_COMMAND_NAME` may not be inlined: the value is the
boundary's to decide, and a copy of today's answer stops being the
answer the moment the boundary's rules change.
"""


def _tool_modules() -> list[Path]:
    return sorted(
        path
        for path in tracked_python_files()
        if path.name == "tool.py"
        and path.parent.parent.name == "features"
        and path.parent.parent.parent.name in discovered_bcs()
    )


def _slice_id(path: Path) -> str:
    rel = path.relative_to(KEEPER_ROOT)
    return f"{rel.parts[0]}/{path.parent.name}"


def _handler_calls(tree: ast.Module) -> list[ast.Call]:
    """Calls to the local name `handler`, which every tool resolves first."""
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "handler"
    ]


def test_the_tool_scan_finds_one_in_every_bounded_context() -> None:
    """Guard the enumeration: an empty parameter set skips, it does not fail."""
    found = _tool_modules()
    contexts = {p.relative_to(KEEPER_ROOT).parts[0] for p in found}
    assert contexts == set(discovered_bcs()), (
        f"tools found in {sorted(contexts)}, bounded contexts are "
        f"{sorted(discovered_bcs())}. The rule below would range over part of the tree."
    )


@pytest.mark.parametrize("tool", _tool_modules(), ids=_slice_id)
def test_a_tool_passes_every_boundary_value_from_its_resolver(tool: Path) -> None:
    calls = _handler_calls(ast.parse(tool.read_text(encoding="utf-8")))
    assert len(calls) == 1, (
        f"{_slice_id(tool)} calls its handler {len(calls)} times. A tool is one "
        "intent through one door, and two calls is a reader asking which of them "
        "the boundary values belong to."
    )

    passed = {kw.arg: kw.value for kw in calls[0].keywords if kw.arg}
    for keyword, resolver in BOUNDARY_RESOLVERS.items():
        value = passed.get(keyword)
        assert value is not None, (
            f"{_slice_id(tool)} does not pass {keyword}= to its handler. All three "
            f"boundary values are required: {sorted(BOUNDARY_RESOLVERS)}."
        )
        supplied_by = (
            value.func.id
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
            else None
        )
        assert supplied_by == resolver, (
            f"{_slice_id(tool)} passes {keyword}={ast.unparse(value)}, which is not "
            f"{resolver}(...). This value is the boundary's to decide and never the "
            "client's to name. The mistake this catches is passing a tool ARGUMENT "
            "here: in grant_permission the word principal_id means the grantee three "
            "lines above and the caller on this line, and swapping them would let "
            "any client act as anyone it can name."
        )
