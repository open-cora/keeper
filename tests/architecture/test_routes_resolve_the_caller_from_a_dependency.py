"""A route takes the caller from a dependency, never from its own parameters.

The tool-side rule next door, in
`test_tools_resolve_the_caller_at_the_boundary.py`, ends by saying it
covers MCP only: a route reaches the same three values through FastAPI
dependencies, which is a different shape with its own failure modes.
This is that shape.

    principal_id    who is calling, from `get_principal_id`
    surface_id      which entrance, from `get_surface_id`
    correlation_id  the trace this call belongs to, from `get_correlation_id`

Everything else in a route signature is the client's: a path segment, a
query parameter, a field off the body. The three above are the door's,
and a route that reads one of them from its own arguments believes
whatever the caller typed.

## The failure this catches, which is already sitting in the tree

`revoke_permission/route.py` declares `principal_id: UUID` as a PATH
parameter, because the thing being revoked is a (principal, command)
pair and the client has to name the principal. It also needs the caller,
so it takes that as `caller_id` and passes `principal_id=caller_id`.

Both names are right and the line between them is one word. Writing
`principal_id=principal_id` there is a natural-looking edit, it
typechecks, every test still passes, and it lets any client revoke a
permission as anyone it can name. Nothing before this file would have
noticed.

## Why the rule is about the dependency and not the name

The obvious rule, that `principal_id=` must receive something called
`principal_id`, would pass that bug and fail the route that avoids it.
So the check resolves the name instead: whatever is passed must be a
parameter the route declared as `Annotated[..., Depends(<resolver>)]`,
with the resolver this boundary value is supposed to come from. That
accepts `caller_id` and `cid`, which are dependency-backed under another
name, and refuses a path parameter whatever it is called.

## A route that reads more than once

`list_executions` holds its request open and re-reads until something
matches, so it calls its handler from a nested reader rather than once
inline. The rule is unchanged by that: the keywords are still written in
one place, and they still name parameters the route declared from
dependencies, because a closure declares none of its own. What the check
does about it is drop nested functions when picking the route and then
range over every handler call inside it.

## Why source and not behaviour

Same reason the tool rule gives. Under the test posture the resolvers
return constants, so a route hardcoding today's constant would behave
identically to one that asked, and a test asserting the value would
agree with either.
"""

import ast
from pathlib import Path

import pytest

from tests.architecture.conftest import KEEPER_ROOT, discovered_bcs, tracked_python_files

pytestmark = pytest.mark.architecture

BOUNDARY_DEPENDENCIES: dict[str, str] = {
    "principal_id": "get_principal_id",
    "surface_id": "get_surface_id",
    "correlation_id": "get_correlation_id",
}
"""Handler keyword to the dependency allowed to supply it.

The same three the MCP rule pins, reached a different way. Keeping the
two dicts separate rather than sharing one is deliberate: they agree on
the keywords and differ on every resolver, and a shared table would have
to be read twice to learn either half.
"""


def _route_modules() -> list[Path]:
    return sorted(
        path
        for path in tracked_python_files()
        if path.name == "route.py"
        and path.parent.parent.name == "features"
        and path.parent.parent.parent.name in discovered_bcs()
    )


def _slice_id(path: Path) -> str:
    rel = path.relative_to(KEEPER_ROOT)
    return f"{rel.parts[0]}/{path.parent.name}"


def _depends_resolver(annotation: ast.expr | None) -> str | None:
    """The name inside `Depends(...)` on an `Annotated[...]` parameter, if any.

    Returns None for a parameter annotated any other way, which is what a
    path, query or body parameter looks like.
    """
    if not isinstance(annotation, ast.Subscript):
        return None
    if not (isinstance(annotation.value, ast.Name) and annotation.value.id == "Annotated"):
        return None
    elements = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else []
    for element in elements:
        if (
            isinstance(element, ast.Call)
            and isinstance(element.func, ast.Name)
            and element.func.id == "Depends"
            and element.args
            and isinstance(element.args[0], ast.Name)
        ):
            return element.args[0].id
    return None


def _handler_calls(node: ast.AST) -> list[ast.Call]:
    return [
        child
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Name)
        and child.func.id == "handler"
    ]


def route_boundary_sources(source: str) -> dict[str, tuple[str, str | None]]:
    """How each boundary value reaches the handler, for the route in `source`.

    Maps the handler keyword to the value as written and to the dependency
    that value was declared from, or None when it was declared some other
    way. A keyword the route never passes is absent from the result.

    Takes source text rather than a path so the check below can be run
    against a route of the caller's choosing, which is the only way to show
    it tells the safe shape from the dangerous one.
    """
    tree = ast.parse(source)
    calling = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and _handler_calls(node)
    ]
    # A route may read through a nested helper, which `ast.walk` reports as a
    # second function calling the handler. The route is the outer one either
    # way: the keywords below are written against parameters it declared, and
    # a closure has none of its own. So the nested ones are dropped rather
    # than counted, and the check runs over every call inside the route.
    nested = {
        inner
        for outer in calling
        for inner in ast.walk(outer)
        if inner is not outer and inner in calling
    }
    functions = [node for node in calling if node not in nested]
    if len(functions) != 1:
        msg = f"expected one function calling the handler, found {len(functions)}"
        raise ValueError(msg)
    route = functions[0]

    arguments = route.args
    declared = {
        argument.arg: _depends_resolver(argument.annotation)
        for argument in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
    }

    calls = _handler_calls(route)
    if len(calls) != 1:
        msg = f"expected one handler call, found {len(calls)}"
        raise ValueError(msg)

    found: dict[str, tuple[str, str | None]] = {}
    for keyword in calls[0].keywords:
        if keyword.arg not in BOUNDARY_DEPENDENCIES:
            continue
        value = keyword.value
        resolver = declared.get(value.id) if isinstance(value, ast.Name) else None
        found[keyword.arg] = (ast.unparse(value), resolver)
    return found


def test_the_route_scan_finds_one_in_every_bounded_context() -> None:
    """Guard the enumeration: an empty parameter set skips, it does not fail."""
    found = _route_modules()
    contexts = {p.relative_to(KEEPER_ROOT).parts[0] for p in found}
    assert contexts == set(discovered_bcs()), (
        f"routes found in {sorted(contexts)}, bounded contexts are "
        f"{sorted(discovered_bcs())}. The rule below would range over part of the tree."
    )


_SAFE_ROUTE = """
async def delete_thing(
    principal_id: UUID,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    caller_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> None:
    await handler(
        Revoke(principal_id=principal_id),
        principal_id=caller_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
"""

_ESCALATING_ROUTE = _SAFE_ROUTE.replace("principal_id=caller_id", "principal_id=principal_id")


def test_the_check_tells_a_dependency_apart_from_a_path_parameter() -> None:
    """Run the reader over both shapes, since the tree only contains one.

    The two sources differ by one word, and that word is the whole bug.
    A rule keyed on the name rather than the dependency would read them
    the same way round and call the dangerous one correct.
    """
    safe = route_boundary_sources(_SAFE_ROUTE)
    assert safe["principal_id"] == ("caller_id", "get_principal_id")
    assert safe["correlation_id"] == ("cid", "get_correlation_id")

    escalating = route_boundary_sources(_ESCALATING_ROUTE)
    assert escalating["principal_id"] == ("principal_id", None)


def test_the_check_reports_a_boundary_value_a_route_never_passes() -> None:
    """A missing keyword is absent, not silently dependency-backed."""
    without_surface = _SAFE_ROUTE.replace("        surface_id=surface_id,\n", "")
    assert "surface_id" not in route_boundary_sources(without_surface)


@pytest.mark.parametrize("route", _route_modules(), ids=_slice_id)
def test_a_route_passes_every_boundary_value_from_its_dependency(route: Path) -> None:
    found = route_boundary_sources(route.read_text(encoding="utf-8"))

    for keyword, dependency in BOUNDARY_DEPENDENCIES.items():
        assert keyword in found, (
            f"{_slice_id(route)} does not pass {keyword}= to its handler. All three "
            f"boundary values are required: {sorted(BOUNDARY_DEPENDENCIES)}. Without "
            "one the handler falls back to its default, and for surface_id that "
            "default is the nil sentinel, which authorize then reads as the "
            "entrance."
        )
        written, resolver = found[keyword]
        assert resolver == dependency, (
            f"{_slice_id(route)} passes {keyword}={written}, which the route did not "
            f"declare as Annotated[..., Depends({dependency})]. This value belongs to "
            "the door, not to the caller, and everything else in a route signature "
            "is a path segment, a query parameter or a body field that the client "
            "filled in. Take it from the dependency, under whatever local name "
            "avoids colliding with the client's own."
        )
