"""Every bounded context in the tree is plugged into the application.

Twelve rules in this directory range over `discovered_bcs()`. All of
them ask whether a bounded context is well formed; none asked whether it
runs. A context could carry perfect slices, pass every structural check,
and never be reachable, because the four lines that mount it live in
`create_app` and nothing compared that list against the tree.

The two pins that would otherwise notice are per-context and written by
hand: the OpenAPI path set and the tool set. For the first context they
happen to list its paths, so deleting its route registration fails. For
a context nobody wrote pins for, the tree gains a package and both pins
stay silent, which is a check whose halves go quiet together.

The sides here are independent. One is the directory tree; the other is
what `create_app` actually calls, read from the source rather than by
running it. A context exists because somebody made a folder and is
mounted because somebody wrote a call, and those are two different acts.

Projections are required only of a context that has any, which is read
from the tree the same way: a projections package means the app has to
register them. The other three plug points are unconditional, because a
context with no routes, no tools and no wiring is not a context.

That conditional used to look for a single module file at the context
root, while docs/reference/layout.md has always drawn the projections as
a package. Neither spelling makes the other's file exist, so the rule
could not fire, and the first context to add projections found that out
by reading this paragraph rather than by a failure. It now looks for
either.

Both spellings stay accepted although only the package is in use. What
is being detected is that a context has projections at all, and a
context with exactly one might reasonably write a module where a context
with several writes a package.

Only one direction is checked here. A call left behind by a context that
was deleted needs no rule: its import at the top of `main.py` would name
a module that is gone, and the application would not load at all.
"""

import ast
from functools import cache

import pytest

from tests.architecture.conftest import KEEPER_ROOT, discovered_bcs

pytestmark = pytest.mark.architecture

_MAIN = KEEPER_ROOT / "api" / "main.py"

_PLUG_POINTS: tuple[tuple[str, str], ...] = (
    ("wire_{bc}", "the handler bundle never reaches app.state, so no route can find it"),
    ("register_{bc}_routes", "the HTTP surface serves none of this context's paths"),
    ("register_{bc}_tools", "the MCP surface publishes none of this context's tools"),
)

_CONDITIONAL: tuple[tuple[str, str, str], ...] = (
    (
        "register_{bc}_projections",
        "projections",
        "the projections this context declares are never subscribed, so its read "
        "models stay empty while every write succeeds",
    ),
)


@cache
def _called_names() -> frozenset[str]:
    """Every plain function name called anywhere in `create_app`'s module.

    Read from the source rather than by importing and running it: the
    question is what the composition root says, and a module that has to
    be executed to be inspected cannot be inspected when it is broken.
    """
    tree = ast.parse(_MAIN.read_text(encoding="utf-8"))
    return frozenset(
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    )


def _has_module(bc: str, name: str) -> bool:
    """Whether a context carries this module, as a file or as a package.

    Both spellings, because the thing being detected is "this context has
    projections" and a package is how a context with more than one of them
    says so. Checking only for `<name>.py` is what made this rule silent.
    """
    root = KEEPER_ROOT / bc
    return (root / f"{name}.py").exists() or (root / name / "__init__.py").exists()


def test_the_mount_scan_finds_a_bounded_context_and_a_composition_root() -> None:
    """Guard both sides: either one empty makes the rule below vacuous."""
    assert discovered_bcs(), "No bounded context found under src/keeper."
    assert _MAIN.exists(), f"{_MAIN} is missing, so there is nothing to read calls from."
    assert _called_names(), (
        f"No plain function call found in {_MAIN.name}, so the call scan has "
        "stopped working and every context would look unmounted."
    )


def _cases() -> list[tuple[str, str, str]]:
    """One case per context and plug point it is required to use."""
    cases: list[tuple[str, str, str]] = []
    for bc in discovered_bcs():
        cases.extend((bc, template.format(bc=bc), why) for template, why in _PLUG_POINTS)
        cases.extend(
            (bc, template.format(bc=bc), why)
            for template, filename, why in _CONDITIONAL
            if _has_module(bc, filename)
        )
    return cases


@pytest.mark.parametrize(
    ("call", "consequence"),
    [(call, why) for _bc, call, why in _cases()],
    ids=[f"{bc}-{call}" for bc, call, _why in _cases()],
)
def test_the_composition_root_calls_every_plug_point_a_context_needs(
    call: str, consequence: str
) -> None:
    assert call in _called_names(), (
        f"{_MAIN.name} never calls {call}().\n"
        f"Consequence: {consequence}.\n"
        "Add the call in create_app, at the plug point its module docstring "
        "names. Nothing else in the tree may import every context, so this is "
        "the one file that has to change when a context lands."
    )
