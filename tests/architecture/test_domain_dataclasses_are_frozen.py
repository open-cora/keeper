"""Domain dataclasses (state, events, commands) must be frozen.

Aggregate state, events and commands are values, not entities. They take
part in replay determinism and in event-store immutability, and their
semantics depend on equality and hashing working from the field tuple.

A mutable dataclass in any of those three breaks both. An evolver can
quietly mutate prior state without emitting an event, so the stream stops
being the whole record. And a frozenset of commands or events can collapse
to a single representative, so a test that builds several and asserts on
the set is asserting on one.

This executions every state, events and command module under a bounded
context and fails on any dataclass decorator that omits `frozen=True`.
Exception subclasses and enums are not dataclasses and are untouched.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

import pytest

from tests.architecture.conftest import KEEPER_ROOT, discovered_bcs, tracked_python_files

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.architecture

_DOMAIN_MODULE_STEMS: frozenset[str] = frozenset({"state", "events"})
"""Aggregate-side modules whose dataclasses are domain values."""


def _is_domain_file(f: Path) -> bool:
    """An aggregate's state or events module, or a slice's command module."""
    if f.stem in _DOMAIN_MODULE_STEMS and "aggregates" in f.parts:
        return True
    return f.stem == "command" and "features" in f.parts


def _domain_files() -> list[Path]:
    tracked = tracked_python_files()
    bc_roots = [KEEPER_ROOT / bc for bc in discovered_bcs()]
    return sorted(
        f
        for f in tracked
        if any(f.is_relative_to(root) for root in bc_roots) and _is_domain_file(f)
    )


def _qualified(p: Path) -> str:
    return "keeper." + ".".join(p.relative_to(KEEPER_ROOT).with_suffix("").parts)


def _dataclass_violations(tree: ast.AST) -> list[str]:
    """One message per dataclass decorator that is not frozen."""
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for decorator in node.decorator_list:
            # The bare decorator form carries no keywords at all, so it is
            # always mutable. Catching it separately gives a message that
            # says which of the two mistakes was made.
            if isinstance(decorator, ast.Name) and decorator.id == "dataclass":
                violations.append(
                    f"line {decorator.lineno}: {node.name} uses the bare decorator "
                    "(implicitly frozen=False); write @dataclass(frozen=True)"
                )
                continue
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            decorator_name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else None
            )
            if decorator_name != "dataclass":
                continue
            frozen_kw = next((kw for kw in decorator.keywords if kw.arg == "frozen"), None)
            if frozen_kw is None:
                violations.append(f"line {decorator.lineno}: {node.name} omits frozen=True")
                continue
            if not (isinstance(frozen_kw.value, ast.Constant) and frozen_kw.value.value is True):
                rendered = ast.unparse(frozen_kw.value)
                violations.append(
                    f"line {decorator.lineno}: {node.name} has frozen={rendered} "
                    "(must be the literal True, not an expression)"
                )
    return violations


def test_the_domain_module_scan_finds_at_least_one_module() -> None:
    """Guard the enumeration: an empty parameter set skips, it does not fail."""
    assert _domain_files(), (
        "No state, events or command module found under any bounded context, "
        "so the frozen rule below ran against nothing."
    )


@pytest.mark.parametrize("path", _domain_files(), ids=_qualified)
def test_a_domain_module_declares_every_dataclass_frozen(path: Path) -> None:
    tree = ast.parse(path.read_text())
    violations = _dataclass_violations(tree)
    assert not violations, (
        f"{_qualified(path)} declares a mutable dataclass:\n  "
        + "\n  ".join(violations)
        + "\nDomain values (state, events, commands) are immutable."
    )
