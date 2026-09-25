"""Every registered projection has a table to write and a cursor to keep.

A projection's name is three things: the registered name the worker
iterates, the `proj_*` table it writes, and the row in
`projection_bookmarks` that says how far it has got. Nothing in the type
system ties the three together, and the two ways they come apart fail
differently and both fail late.

    no table      the first apply raises inside the worker's backoff
                  loop, forever, while every write succeeds
    no bookmark   the first advance raises `MissingBookmarkError`, same
                  loop, same silence

Neither shows up in a request. A deployment with either one boots, serves,
writes, and quietly answers reads out of a table that is missing or empty.

This check was promised twice before anything could run it, in
docs/reference/patterns.md and in the `Projection` Protocol's own
docstring, both saying it belonged with the first projection. This is that
projection's commit.

## Registration is read from the registrars, not by importing

The BC's `register_<bc>_projections` is parsed rather than called, the way
`test_every_bc_is_mounted.py` reads the composition root. Calling it would
need a `Kernel`, and a check about what the source says should not need
the application to be constructible to say it.

The registrar is `projections/register.py`, inside the package it
registers rather than at the context root. That module's docstring
carries the reasoning; what matters here is only that the path below is
where the registrations are written down.
"""

import ast
import re

import pytest

from tests.architecture.conftest import (
    KEEPER_ROOT,
    discovered_bcs,
    tracked_migration_files,
)

pytestmark = pytest.mark.architecture

_CREATE_TABLE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(proj_[a-z0-9_]+)",
    re.IGNORECASE,
)
_SEEDS_BOOKMARK = re.compile(
    r"INSERT\s+INTO\s+projection_bookmarks[^;]*?'([a-z0-9_]+)'",
    re.IGNORECASE | re.DOTALL,
)


def _registrars() -> list[tuple[str, ast.Module]]:
    """Each bounded context's projection registrar, parsed.

    A context with no projections has no such package and contributes
    nothing, which is the same shape the mount check uses: the rule
    applies to a context that has projections rather than requiring one
    of every context.
    """
    found: list[tuple[str, ast.Module]] = []
    for bc in sorted(discovered_bcs()):
        path = KEEPER_ROOT / bc / "projections" / "register.py"
        if path.exists():
            found.append((bc, ast.parse(path.read_text(encoding="utf-8"))))
    return found


def _registered_class_names(tree: ast.Module) -> list[str]:
    """Classes handed to `registry.register(...)` in a registrar."""
    return [
        node.args[0].func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "register"
        if node.args
        if isinstance(node.args[0], ast.Call) and isinstance(node.args[0].func, ast.Name)
    ]


def _string_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level `NAME = "literal"` assignments."""
    return {
        target.id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
        for target in node.targets
        if isinstance(target, ast.Name)
    }


def _declared_name(bc: str, class_name: str) -> str | None:
    """The `name` a projection class assigns, read from its own module.

    Found by searching the context's `projections` package for the class
    rather than by importing it, and returning None when the value is
    neither a string literal nor a module constant holding one, which the
    check below reports rather than skipping.

    Following a constant matters because naming the string once is the
    right way to write it: the same value has to reach the migration and
    the query, and a class repeating the literal is the drift this whole
    file exists to catch.
    """
    for path in sorted((KEEPER_ROOT / bc / "projections").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        constants = _string_constants(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or node.name != class_name:
                continue
            for statement in node.body:
                if not isinstance(statement, ast.Assign) or not any(
                    isinstance(target, ast.Name) and target.id == "name"
                    for target in statement.targets
                ):
                    continue
                value = statement.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    return value.value
                if isinstance(value, ast.Name):
                    return constants.get(value.id)
    return None


def _registered_projection_names() -> dict[str, str]:
    """Registered projection name, keyed by the class that declares it."""
    names: dict[str, str] = {}
    for bc, tree in _registrars():
        for class_name in _registered_class_names(tree):
            declared = _declared_name(bc, class_name)
            if declared is not None:
                names[class_name] = declared
    return names


def _migration_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in tracked_migration_files())


def test_at_least_one_projection_is_registered() -> None:
    """Guard the enumeration. With no projections the two checks below
    range over nothing and pass while examining nothing, which is the
    failure mode `test_fitness_scope.py` exists to name."""
    assert _registered_projection_names(), (
        "No registered projection was discovered, so the checks below examine "
        "nothing. A context registering one declares it in its "
        "projections package with a class whose `name` is a plain string."
    )


def test_every_registered_projection_has_a_table_some_migration_creates() -> None:
    created = set(_CREATE_TABLE.findall(_migration_text()))
    missing = {
        class_name: name
        for class_name, name in _registered_projection_names().items()
        if name not in created
    }
    assert not missing, (
        "Projections registered with no matching CREATE TABLE in any migration. "
        "The worker writes to a table that is not there and fails inside its "
        f"own backoff loop while every write succeeds: {missing}"
    )


def test_every_registered_projection_has_a_bookmark_some_migration_seeds() -> None:
    seeded = set(_SEEDS_BOOKMARK.findall(_migration_text()))
    missing = {
        class_name: name
        for class_name, name in _registered_projection_names().items()
        if name not in seeded
    }
    assert not missing, (
        "Projections registered with no INSERT INTO projection_bookmarks in any "
        "migration. The first advance raises MissingBookmarkError forever and "
        f"the read model stays empty: {missing}"
    )
