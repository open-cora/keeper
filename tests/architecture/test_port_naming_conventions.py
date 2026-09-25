"""Port module and Protocol names follow the seam vocabulary.

Three rules, all about a port being findable from the thing it abstracts:

  - A port module is `snake_case` of its Protocol (`event_store.py` defines
    `EventStore`), so knowing either name gives you the other.
  - No Protocol carries a `Port` suffix. Every Protocol in this package is a
    port; saying so distinguishes nothing. The module path already reads
    `infrastructure.ports.event_store`.
  - A cross-BC read port is named `<Thing>Lookup`. None exist yet, so that
    rule currently ranges over nothing and is stated here as the shape the
    first one should take rather than as a check that is doing work.
"""

import ast
from pathlib import Path

import pytest

from tests.architecture.conftest import KEEPER_ROOT

pytestmark = pytest.mark.architecture

PORTS_DIR = KEEPER_ROOT / "infrastructure" / "ports"

ACRONYMS: dict[str, str] = {}
"""Module stems whose Protocol is not a plain title-case of the stem.

Empty. Its only entry was the language-model port, whose stem title-cased to
the wrong thing, and that port is gone. Kept as data rather than a special
case in the comparison so the next acronym costs one line, not a branch."""


def _port_modules() -> list[Path]:
    return sorted(p for p in PORTS_DIR.glob("*.py") if p.name != "__init__.py")


def _protocols(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and not node.name.startswith("_")
        and any(
            (isinstance(b, ast.Name) and b.id == "Protocol")
            or (isinstance(b, ast.Attribute) and b.attr == "Protocol")
            for b in node.bases
        )
    ]


def test_ports_directory_holds_modules_to_check() -> None:
    """Guard the enumeration, so the checks below cannot pass vacuously."""
    assert _port_modules(), "No port modules found; the checks below examine nothing."


def test_no_protocol_carries_a_port_suffix() -> None:
    offenders = [
        f"{path.name}:{name}"
        for path in _port_modules()
        for name in _protocols(path)
        if name.endswith("Port")
    ]
    assert not offenders, (
        f"Protocols carrying a redundant `Port` suffix: {offenders}. "
        "Everything in this package is a port; the module path says so."
    )


def test_each_port_module_is_snake_case_of_a_protocol_it_defines() -> None:
    offenders: list[str] = []
    for path in _port_modules():
        names = _protocols(path)
        if not names:
            continue  # covered by test_port_structure
        stem = path.stem
        expected = ACRONYMS.get(stem, stem.replace("_", ""))
        if not any(name.lower() == expected.lower() for name in names):
            offenders.append(f"{path.name} defines {names}")
    assert not offenders, (
        "Port modules whose filename matches no Protocol they define:\n"
        + "\n".join(f"  {o}" for o in offenders)
    )


def test_cross_bc_lookup_ports_are_named_lookup() -> None:
    """A cross-BC read port reads `<Thing>Lookup`.

    Vacuous today, though no longer for want of bounded contexts. None of
    them declares a cross-BC read port: the one that reads a sibling imports
    `load_actor` through the door tach opens, which leaves no port to name.
    The rule is here so the first one lands named correctly rather than
    being renamed afterwards, and it costs nothing while the set is empty.
    """
    offenders: list[str] = []
    for path in _port_modules():
        if not path.stem.endswith("_lookup"):
            continue
        for name in _protocols(path):
            if not name.endswith(("Lookup", "LookupResult")):
                offenders.append(f"{path.name}:{name}")
    assert not offenders, (
        f"Protocols in a `*_lookup.py` module not named `<Thing>Lookup`: {offenders}"
    )
