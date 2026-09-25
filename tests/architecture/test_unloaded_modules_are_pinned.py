"""Modules the application never loads, written down so the set can shrink.

The chassis was copied from a sibling project with more domains in it.
Some of what came along has no user here yet, which was the plan: the
alternative was deciding in advance which pieces the first bounded
context would want. That decision is now due, one piece at a time, and
the moment it is due for any given module is the moment something starts
importing it.

This is the check that notices that moment. The pin below is a snapshot
of a transition, not a list of exceptions: nothing in it is a standing
judgement that a module should stay unused, every entry means the same
thing, and the target is for the set to empty. When a context starts
using one, this fails and names it, which is the news worth having.

Loading, not using. A module counts as loaded if importing the
application would execute it, which includes being re-exported by a
package that something else imports. `projection/cursor.py` and
`projection/drain.py` are exactly that case: nothing calls them, and
they run at startup anyway because `projection/__init__.py` pulls them
in. An earlier hand-rolled version of this execution missed the package
chain and called both of them unreachable, which was wrong by 208 lines.
The table below exists because of that mistake.

One entry point, and it stays one. An execution from `main.py` alone reaches
every bounded context, because `test_every_bc_is_mounted.py` requires
`create_app` to call into each of them. The two rules hold each other
up: unmount a context and that one fails loudly, rather than this one
quietly reporting the whole context as dead.
"""

import ast
from collections.abc import Mapping
from functools import cache
from pathlib import Path

import pytest

from tests.architecture.conftest import SRC_ROOT, tracked_python_files

pytestmark = pytest.mark.architecture

ENTRY_POINT = "keeper.api.main"
"""The module an operator runs. Everything the app does hangs off it."""

NEVER_LOADED: frozenset[str] = frozenset(
    {
        "keeper.shared.identity",
        "keeper.shared.json_merge_patch",
        "keeper.shared.path_segment",
    }
)
"""Every module the running application does not execute. 174 lines.

Three entries left, down from eight. The Execution context took the
other five across two landings: the Plan holds a bounded name and
declares a JSON Schema, which loaded `bounded_text` and the three
`json_schema` modules, and the Run carries an external reference, which
loaded `identifier`. That is the shape the entries above are waiting
for, an aggregate that models the thing rather than a context that
happens to exist.

Two slice helpers used to be in this set and are deleted rather than
still waiting. The prediction written beside them, that a second context
was most likely to reach for the list-query and update-handler machinery
first, is why the entries above are worth reading as a record and not as
a forecast: two more contexts landed and neither reached for either. A
pin says what is unused, which is evidence. It cannot say what will be
wanted.

Removing an entry is the good case and means something started using it.
Adding one means new code arrived with no caller, which is worth a
sentence in the commit message either way.
"""


def _ancestors(module: str) -> list[str]:
    """Packages Python executes on the way to importing `module`.

    Importing `a.b.c` runs `a` and `a.b` first, and whatever those two
    import runs with them. Skipping this step is what made an earlier
    version of this execution wrong.
    """
    parts = module.split(".")
    return [".".join(parts[:index]) for index in range(1, len(parts))]


def reachable(entry: str, edges: Mapping[str, frozenset[str]]) -> frozenset[str]:
    """Modules executed by importing `entry`, given what each one imports.

    Takes the graph rather than reading the tree, so the table below can
    run it over shapes this repository does not currently contain. A
    name that is not a key is something outside the package and is
    ignored rather than followed.
    """
    seen: set[str] = set()
    stack = [entry]
    while stack:
        module = stack.pop()
        if module in seen or module not in edges:
            continue
        seen.add(module)
        stack.extend(edges[module])
        stack.extend(_ancestors(module))
    return frozenset(seen)


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(SRC_ROOT).with_suffix("").parts).removesuffix(".__init__")


def _imports(path: Path) -> frozenset[str]:
    """Every in-package module name a file imports.

    `from x import y` contributes both `x` and `x.y`, because the name
    may be a submodule or may be a symbol inside `x`, and only one of
    those will turn out to be a real module.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("keeper"):
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            found.update(a.name for a in node.names if a.name.startswith("keeper"))
    return frozenset(found)


@cache
def _edges() -> dict[str, frozenset[str]]:
    """The import graph of the tracked tree, keyed by module name."""
    return {_module_name(path): _imports(path) for path in tracked_python_files()}


@cache
def _never_loaded() -> frozenset[str]:
    return frozenset(_edges()) - reachable(ENTRY_POINT, _edges())


def test_the_module_scan_finds_the_entry_point_and_most_of_the_tree() -> None:
    """Guard the derivation: an execution that finds nothing calls everything dead.

    The lower bound is deliberately loose. It is not a coverage target,
    only a floor beneath which the execution has plainly stopped working and
    the pin below would be comparing the whole tree against eleven names.
    """
    edges = _edges()
    assert ENTRY_POINT in edges, f"{ENTRY_POINT} is not in the tracked tree."
    loaded = reachable(ENTRY_POINT, edges)
    assert len(loaded) > len(edges) // 2, (
        f"Only {len(loaded)} of {len(edges)} modules came back as loaded, "
        "so the import execution has stopped following edges."
    )


_GRAPHS: tuple[tuple[str, str, dict[str, frozenset[str]], frozenset[str]], ...] = (
    (
        "a plain chain",
        "a",
        {"a": frozenset({"b"}), "b": frozenset()},
        frozenset({"a", "b"}),
    ),
    (
        "a module nobody imports",
        "a",
        {"a": frozenset(), "b": frozenset()},
        frozenset({"a"}),
    ),
    (
        "a package runs before its submodule",
        "p.m",
        {"p": frozenset(), "p.m": frozenset()},
        frozenset({"p", "p.m"}),
    ),
    (
        "a package re-export loads a sibling",
        "p.m",
        {"p": frozenset({"p.x"}), "p.m": frozenset(), "p.x": frozenset()},
        frozenset({"p", "p.m", "p.x"}),
    ),
    (
        "a cycle terminates",
        "a",
        {"a": frozenset({"b"}), "b": frozenset({"a"})},
        frozenset({"a", "b"}),
    ),
    (
        "a name outside the package is ignored",
        "a",
        {"a": frozenset({"elsewhere.thing"})},
        frozenset({"a"}),
    ),
)


@pytest.mark.parametrize(
    ("entry", "edges", "expected"),
    [(entry, edges, expected) for _label, entry, edges, expected in _GRAPHS],
    ids=[label for label, _e, _g, _x in _GRAPHS],
)
def test_the_walk_executes_what_python_would_execute(
    entry: str, edges: dict[str, frozenset[str]], expected: frozenset[str]
) -> None:
    """Run the execution over graphs of this table's choosing, not the tree's.

    The fourth row is the one that matters. A package that re-exports a
    module keeps it loaded even though nothing calls it, and an execution blind
    to that reports live code as dead. It did, before this row existed.
    """
    assert reachable(entry, edges) == expected


def test_the_set_of_never_loaded_modules_matches_the_pin() -> None:
    found = _never_loaded()
    assert found == NEVER_LOADED, (
        "The set of modules the application never loads has changed.\n"
        f"  now used:  {sorted(NEVER_LOADED - found)}\n"
        f"  now unused: {sorted(found - NEVER_LOADED)}\n\n"
        "Something starting to be used is the good case: drop it from "
        "NEVER_LOADED and say in the commit message what reached for it. "
        "Something newly unused means code landed with no caller, which is "
        "worth a sentence either way."
    )
