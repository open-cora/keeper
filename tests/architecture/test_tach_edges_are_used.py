"""Every permission tach.toml grants is taken up by a real import.

Two kinds are granted here, and both go stale the same way. A
`depends_on` edge says one module may reach another; an `[[interfaces]]`
`expose` entry says which names it may reach when it gets there.

tach enforces that nothing imports what it may not. It says nothing about the
reverse: a permission granted for a reason that has since gone away stays in
the file forever, and the contract slowly stops describing the system.

The asymmetry matters because the two errors have different costs. A missing
permission fails loudly the moment someone adds the import. A stale one fails
never, and quietly widens what the next author is allowed to do.

The interface check matters more than the edge check, for one reason. An
interface is sized by reading what its consumer imports, which is the only
honest way to size a public surface, and that claim is true on the day it is
written and untrue the moment the consumer stops importing something. An
expose entry nobody takes up is a door left open for a visitor who left.

## What this cannot see

tach constrains IMPORTS, and an import is only one of the ways one module
comes to depend on another. A Protocol declared in `infrastructure.ports`,
implemented by one BC and consumed by another, creates a real dependency that
leaves no import to constrain: both sides name only `keeper.infrastructure`.
So a green run here means the declared edges are all used, NOT that the
declared edges are all the dependencies.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import ast
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

from tests.architecture.conftest import tracked_python_files

pytestmark = pytest.mark.architecture

TACH_TOML = "tach.toml"


def _modules() -> list[dict[str, Any]]:
    from tests.architecture.conftest import SRC_ROOT

    path = SRC_ROOT.parent / TACH_TOML
    modules: list[dict[str, Any]] = tomllib.loads(path.read_text())["modules"]
    return modules


def test_tach_declares_at_least_one_module() -> None:
    """Guard the enumeration, so the check below cannot pass vacuously."""
    assert _modules(), "tach.toml declares no modules; the check below examines nothing."


def test_every_declared_dependency_edge_is_taken_up_by_an_import() -> None:
    modules = _modules()
    sources = {p: p.read_text() for p in tracked_python_files()}

    unused: list[str] = []
    for module in modules:
        owner = str(module["path"])
        owner_prefix = owner + "."
        for target in module.get("depends_on", []) or []:
            target = str(target)
            # An import of the target from anywhere inside the owning module.
            pattern = re.compile(
                rf"^\s*(?:from\s+{re.escape(target)}[\s.]|import\s+{re.escape(target)}\b)",
                re.MULTILINE,
            )
            taken_up = any(
                pattern.search(text)
                for path, text in sources.items()
                if _module_of(path) == owner or _module_of(path).startswith(owner_prefix)
            )
            if not taken_up:
                unused.append(f"{owner} -> {target}")

    assert not unused, (
        "tach.toml grants dependency edges no source file takes up:\n"
        + "\n".join(f"  {u}" for u in unused)
        + "\nRemove the edge, or add the import that justified it. A permission "
        "whose reason has gone away should not quietly stay."
    )


def _module_of(path: Path) -> str:
    """Map a source path to the dotted module prefix tach would attribute it to."""
    from tests.architecture.conftest import SRC_ROOT

    rel = str(path).removeprefix(str(SRC_ROOT) + "/").removesuffix(".py")
    return rel.replace("/__init__", "").replace("/", ".")


def _interfaces() -> list[dict[str, Any]]:
    from tests.architecture.conftest import SRC_ROOT

    path = SRC_ROOT.parent / TACH_TOML
    declared: list[dict[str, Any]] = tomllib.loads(path.read_text()).get("interfaces", [])
    return declared


def _imported_symbols(module_prefix: str) -> set[str]:
    """Every `from X import y` pair, as `X.y`, written inside one module."""
    prefix = module_prefix + "."
    found: set[str] = set()
    for path in tracked_python_files():
        owner = _module_of(path)
        if owner != module_prefix and not owner.startswith(prefix):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                found |= {f"{node.module}.{alias.name}" for alias in node.names}
    return found


def test_tach_declares_at_least_one_scoped_interface() -> None:
    """Guard the enumeration below, and the claim the interface rests on.

    An interface with no `visibility` applies to every consumer, so its
    expose list cannot be read off one of them. The check below only
    means anything for scoped ones, and an empty set makes it vacuous.
    """
    scoped = [i for i in _interfaces() if i.get("visibility")]
    assert scoped, (
        "tach.toml declares no interface scoped with `visibility`, so the check "
        "below examines nothing."
    )


def test_every_exposed_name_is_taken_up_by_the_consumer_it_was_opened_for() -> None:
    unused: list[str] = []
    for interface in _interfaces():
        consumers = [str(v) for v in interface.get("visibility", []) or []]
        if not consumers:
            continue
        taken_up: set[str] = set()
        for consumer in consumers:
            taken_up |= _imported_symbols(consumer)
        for source in (str(f) for f in interface.get("from", []) or []):
            for entry in (str(e) for e in interface.get("expose", []) or []):
                # `expose` entries are regexes matched against the name
                # relative to the module the interface describes.
                pattern = re.compile(rf"{re.escape(source)}\.{entry}")
                if not any(pattern.fullmatch(symbol) for symbol in taken_up):
                    unused.append(f"{source} exposes {entry} to {', '.join(consumers)}")

    assert not unused, (
        "tach.toml exposes names no permitted consumer imports:\n"
        + "\n".join(f"  {u}" for u in unused)
        + "\nNarrow the expose list, or add the import that justified the entry. "
        "An interface is sized by what its consumer actually reaches for, and "
        "an entry nobody takes up is a wider door than anyone asked for."
    )
