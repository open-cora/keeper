"""Ports are Protocols, and the package re-exports exactly what it defines.

Two rules, both about keeping the seam honest:

  - Every module under `infrastructure/ports/` defines at least one
    `Protocol`. A module there that defines only dataclasses is a types
    module wearing a port's name.
  - `ports/__init__.py` re-exports every public Protocol. A port reachable
    only by its full module path is one consumers will import inconsistently,
    and the inconsistency is what makes a later move painful.
"""

import ast
from pathlib import Path

import pytest

from keeper.infrastructure import ports
from tests.architecture.conftest import KEEPER_ROOT

pytestmark = pytest.mark.architecture

PORTS_DIR = KEEPER_ROOT / "infrastructure" / "ports"


def _port_modules() -> list[Path]:
    return sorted(p for p in PORTS_DIR.glob("*.py") if p.name != "__init__.py")


def test_ports_directory_is_not_empty() -> None:
    """Guard the enumeration, so the checks below cannot pass vacuously."""
    assert _port_modules(), "No port modules found; the checks below examine nothing."


def test_every_port_module_defines_a_protocol() -> None:
    offenders: list[str] = []
    for path in _port_modules():
        tree = ast.parse(path.read_text())
        has_protocol = any(
            isinstance(node, ast.ClassDef)
            and any(
                (isinstance(base, ast.Name) and base.id == "Protocol")
                or (isinstance(base, ast.Attribute) and base.attr == "Protocol")
                for base in node.bases
            )
            for node in ast.walk(tree)
        )
        if not has_protocol:
            offenders.append(path.name)
    assert not offenders, (
        f"Port modules defining no Protocol (a types module in a port's clothing): {offenders}"
    )


def test_every_port_protocol_is_reexported_from_the_package() -> None:
    exported = set(ports.__all__)
    missing: list[str] = []
    for path in _port_modules():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or node.name.startswith("_"):
                continue
            is_protocol = any(
                (isinstance(base, ast.Name) and base.id == "Protocol")
                or (isinstance(base, ast.Attribute) and base.attr == "Protocol")
                for base in node.bases
            )
            if is_protocol and node.name not in exported:
                missing.append(f"{path.name}:{node.name}")
    assert not missing, (
        f"Protocols not re-exported from keeper.infrastructure.ports.__all__: {missing}"
    )
