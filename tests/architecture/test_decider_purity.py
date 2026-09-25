"""Deciders are pure: no I/O, no clock, no randomness, no generated ids.

A decider is replayed. Its job is to turn stored state plus a command into
events, and that has to give the same answer every time it runs, years
apart, against the same inputs. Anything the decider invents for itself
is a value replay cannot reproduce, so every non-deterministic input is
injected by the handler as a parameter and captured in the event payload:
the decider receives `now` and `new_id`, it does not go and get them.

This scans every slice's decider module with AST and rejects forbidden
imports and calls. It reads
shape, not behaviour: a decider that reaches for the clock through a
helper this list does not name still passes. The list covers the ways
it actually happens.
"""

import ast
from pathlib import Path

import pytest

from tests.architecture.conftest import KEEPER_ROOT, discovered_bcs, tracked_python_files

pytestmark = pytest.mark.architecture

_FORBIDDEN_TOP_LEVEL_IMPORTS: frozenset[str] = frozenset(
    {
        "asyncpg",
        "httpx",
        "requests",
        "urllib",
        "anthropic",
        "openai",
        "boto3",
        "psycopg",
        "psycopg2",
        "redis",
        "kafka",
        "asyncio",  # deciders are sync
        "subprocess",
        "socket",
        "tempfile",
        "shutil",
        "os",  # filesystem; a decider has no business there
    }
)

_FORBIDDEN_ATTR_CALLS: frozenset[tuple[str, str]] = frozenset(
    {
        ("datetime", "now"),
        ("datetime", "utcnow"),
        ("datetime", "today"),
        ("uuid", "uuid1"),
        ("uuid", "uuid3"),
        ("uuid", "uuid4"),
        ("uuid", "uuid5"),
        ("uuid", "uuid6"),
        ("uuid", "uuid7"),
        ("uuid", "uuid8"),
        ("uuid_utils", "uuid7"),
        ("time", "time"),
        ("time", "monotonic"),
        ("time", "sleep"),
        ("random", "random"),
        ("random", "randint"),
        ("random", "choice"),
        ("os", "getenv"),
        ("os", "environ"),
        ("Path", "read_text"),
        ("Path", "write_text"),
    }
)
"""Object-and-attribute pairs banned inside a decider."""

_FORBIDDEN_BARE_CALLS: frozenset[str] = frozenset(
    {
        "uuid1",
        "uuid3",
        "uuid4",
        "uuid5",
        "uuid6",
        "uuid7",
        "uuid8",
        "open",
        "input",
        "getenv",
    }
)
"""Bare names banned inside a decider, for the from-import spelling."""


def _decider_files() -> list[Path]:
    tracked = tracked_python_files()
    out: list[Path] = []
    for bc in discovered_bcs():
        features = KEEPER_ROOT / bc / "features"
        out.extend(
            sorted(
                f
                for f in tracked
                if f.name == "decider.py"
                and f.parent.parent == features
                and not f.parent.name.startswith("_")
            )
        )
    return out


def _qualified(p: Path) -> str:
    return "keeper." + ".".join(p.relative_to(KEEPER_ROOT).with_suffix("").parts)


def test_the_decider_scan_finds_at_least_one_decider() -> None:
    """Guard the enumeration: an empty parameter set skips, it does not fail."""
    assert _decider_files(), (
        "No decider module found under any bounded context's features/ "
        "directory, so the purity rule below ran against nothing."
    )


@pytest.mark.parametrize("decider", _decider_files(), ids=_qualified)
def test_a_decider_performs_no_io_and_invents_no_values(decider: Path) -> None:
    tree = ast.parse(decider.read_text())
    qualified = _qualified(decider)
    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _FORBIDDEN_TOP_LEVEL_IMPORTS:
                    violations.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            top = node.module.split(".")[0]
            if top in _FORBIDDEN_TOP_LEVEL_IMPORTS:
                violations.append(f"line {node.lineno}: from {node.module} import ...")

        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                pair = (func.value.id, func.attr)
                if pair in _FORBIDDEN_ATTR_CALLS:
                    violations.append(f"line {node.lineno}: {pair[0]}.{pair[1]}()")
            elif isinstance(func, ast.Name) and func.id in _FORBIDDEN_BARE_CALLS:
                violations.append(f"line {node.lineno}: {func.id}()")

    assert not violations, (
        f"{qualified} is not a pure decider:\n  " + "\n  ".join(violations) + "\n"
        "Take the value as a keyword parameter from the handler instead, so "
        "replay sees the same value the original run did."
    )
